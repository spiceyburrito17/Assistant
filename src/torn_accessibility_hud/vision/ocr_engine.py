"""CUDA-configured EasyOCR processing and background worker."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import AppConfig, OCRConfig, RegionsConfig
from ..diagnostics import debug_log, exception_log, write_startup_log
from ..models import OCRBatch, OCRLine
from .capture import ScreenCapture
from .debounce import StableFrameDebouncer

CARD_RANK_ALLOWLIST = "0123456789AaKkQqJjTt"


class EasyOCREngine:
    """Lazy EasyOCR wrapper configured for local GPU acceleration."""

    def __init__(self, config: OCRConfig | None = None) -> None:
        self.config = config or OCRConfig()
        self._reader: Any | None = None

    @property
    def reader(self) -> Any:
        if self._reader is None:
            try:
                debug_log("EasyOCR Reader initializing languages=%s gpu=%s", self.config.languages, self.config.gpu)
                import easyocr

                self._reader = easyocr.Reader(list(self.config.languages), gpu=self.config.gpu)
                debug_log("EasyOCR Reader initialized successfully")
            except Exception as exc:  # noqa: BLE001 - print daemon-thread init failures
                exception_log("EasyOCR Reader initialization FAILED: %s", exc)
                raise
        return self._reader

    def read(
        self,
        frame: np.ndarray[Any, Any],
        allowlist: str | None = None,
        min_confidence: float | None = None,
    ) -> tuple[OCRLine, ...]:
        raw_lines = self.read_raw(frame, allowlist=allowlist)
        confidence_floor = self.config.min_confidence if min_confidence is None else min_confidence
        return tuple(line for line in raw_lines if line.confidence >= confidence_floor)

    def read_raw(self, frame: np.ndarray[Any, Any], allowlist: str | None = None) -> tuple[OCRLine, ...]:
        """Return EasyOCR results before any confidence filtering."""

        kwargs: dict[str, Any] = {"detail": 1, "paragraph": self.config.paragraph}
        if allowlist:
            kwargs["allowlist"] = allowlist
        results = self.reader.readtext(frame, **kwargs)
        lines: list[OCRLine] = []
        for result in results:
            if len(result) < 3:
                continue
            bbox_raw, text, confidence = result[0], str(result[1]), float(result[2])
            bbox = tuple((int(point[0]), int(point[1])) for point in bbox_raw)
            lines.append(OCRLine(text=text, confidence=confidence, bbox=bbox))
        return tuple(sorted(lines, key=lambda line: (line.bbox[0][1] if line.bbox else 0, line.bbox[0][0] if line.bbox else 0)))


def normalize_card_rank(raw_text: str) -> str | None:
    cleaned = raw_text.upper().replace(" ", "").replace("|", "I")
    cleaned = cleaned.replace("O", "0")
    if cleaned in {"10", "I0"}:
        return "T"
    if cleaned == "1":
        return "T"
    if cleaned in {"A", "K", "Q", "J", "T"}:
        return cleaned
    if cleaned in {"2", "3", "4", "5", "6", "7", "8", "9"}:
        return cleaned
    return None


def format_raw_ocr_debug_lines(label: str, lines: tuple[OCRLine, ...], allowlist: str | None) -> tuple[str, ...]:
    debug_lines = [f"[{label}] allowlist={allowlist or '<none>'} raw_count={len(lines)}"]
    if not lines:
        debug_lines.append("  (no raw OCR results)")
        return tuple(debug_lines)
    for index, line in enumerate(lines):
        debug_lines.append(
            f"  #{index} text={line.text!r} confidence={line.confidence:.4f} bbox={line.bbox}"
        )
    return tuple(debug_lines)


def detect_suit_from_card_image(card_bgr: np.ndarray[Any, Any]) -> str | None:
    """Infer suit from the dominant colored suit glyph in a card face crop."""

    suit, _debug_lines = detect_suit_from_card_image_with_debug(card_bgr)
    return suit


def detect_suit_from_card_image_with_debug(card_bgr: np.ndarray[Any, Any]) -> tuple[str | None, tuple[str, ...]]:
    """Infer suit and report dominant color data for dark-theme tuning."""

    import cv2

    if card_bgr.size == 0:
        return None, ("[suit color] SKIPPED - empty crop",)
    sample = card_bgr[: max(1, int(card_bgr.shape[0] * 0.45)), : max(1, int(card_bgr.shape[1] * 0.45))]
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    bgr_mean = tuple(float(value) for value in np.mean(sample.reshape(-1, 3), axis=0))
    hsv_mean = tuple(float(value) for value in np.mean(hsv.reshape(-1, 3), axis=0))
    dominant_bgr, dominant_hsv, dominant_count = _dominant_non_background_color(sample)
    masks = {
        # Hearts stay red in Torn's card themes.
        "h": cv2.inRange(hsv, (0, 55, 45), (14, 255, 255)) | cv2.inRange(hsv, (168, 55, 45), (180, 255, 255)),
        # Diamonds are usually blue in four-color decks, but may appear red/yellow.
        "d": (
            cv2.inRange(hsv, (85, 45, 45), (135, 255, 255))
            | cv2.inRange(hsv, (15, 45, 80), (35, 255, 255))
        ),
        # Clubs are green, sometimes very light in dark mode.
        "c": cv2.inRange(hsv, (35, 35, 40), (90, 255, 255)),
    }
    scores = {suit: int(mask.sum() // 255) for suit, mask in masks.items()}
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    # Spades are black in light mode, but white/light-grey in Torn dark mode.
    dark_score = int(cv2.inRange(gray, 0, 95).sum() // 255)
    light_neutral_mask = cv2.inRange(hsv, (0, 0, 145), (180, 80, 255))
    light_neutral_score = int(light_neutral_mask.sum() // 255)
    scores["s"] = max(dark_score, light_neutral_score)
    best_suit, best_score = max(scores.items(), key=lambda item: item[1])
    debug_lines = [
        "[suit color] "
        f"sample_size={sample.shape[1]}x{sample.shape[0]} "
        f"mean_bgr=({bgr_mean[0]:.1f},{bgr_mean[1]:.1f},{bgr_mean[2]:.1f}) "
        f"mean_hsv=({hsv_mean[0]:.1f},{hsv_mean[1]:.1f},{hsv_mean[2]:.1f})",
        "[suit color] "
        f"dominant_bgr=({dominant_bgr[0]},{dominant_bgr[1]},{dominant_bgr[2]}) "
        f"dominant_hsv=({dominant_hsv[0]},{dominant_hsv[1]},{dominant_hsv[2]}) "
        f"dominant_count={dominant_count}",
        "[suit color] "
        f"scores hearts={scores['h']} diamonds={scores['d']} clubs={scores['c']} "
        f"spades={scores['s']} dark_spade={dark_score} light_spade={light_neutral_score}",
    ]
    if best_score >= 8:
        debug_lines.append(f"[suit color] matched suit={best_suit} score={best_score}")
        return best_suit, tuple(debug_lines)
    debug_lines.append(f"[suit color] FAILED - best_suit={best_suit} best_score={best_score} threshold=8")
    return None, tuple(debug_lines)


def _dominant_non_background_color(sample_bgr: np.ndarray[Any, Any]) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    import cv2

    if sample_bgr.size == 0:
        return (0, 0, 0), (0, 0, 0), 0
    hsv = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    gray = cv2.cvtColor(sample_bgr, cv2.COLOR_BGR2GRAY)
    foreground = (saturation > 30) | (value < 105) | ((value > 145) & (saturation < 85))
    if not np.any(foreground):
        foreground = np.ones(sample_bgr.shape[:2], dtype=bool)
    pixels = sample_bgr[foreground]
    quantized = (pixels // 16) * 16
    colors, counts = np.unique(quantized.reshape(-1, 3), axis=0, return_counts=True)
    best_index = int(np.argmax(counts))
    dominant_bgr = tuple(int(value) for value in colors[best_index])
    dominant_hsv_raw = cv2.cvtColor(np.uint8([[dominant_bgr]]), cv2.COLOR_BGR2HSV)[0, 0]
    dominant_hsv = tuple(int(value) for value in dominant_hsv_raw)
    return dominant_bgr, dominant_hsv, int(counts[best_index])


def detect_suit_near_rank_bbox(
    region_bgr: np.ndarray[Any, Any],
    bbox: tuple[tuple[int, int], ...],
    ocr_scale: float,
) -> tuple[str | None, tuple[str, ...]]:
    """Infer suit by sampling small raw-image ROIs around/below an OCR rank bbox."""

    debug_lines: list[str] = []
    if region_bgr.size == 0:
        return None, ("[bbox fallback] SKIPPED suit detection - region image is empty",)
    rank_box = _scaled_bbox_bounds(bbox, scale=max(ocr_scale, 1.0), image_shape=region_bgr.shape)
    if rank_box is None:
        return None, (f"[bbox fallback] SKIPPED suit detection - invalid bbox={bbox}",)
    x0, y0, x1, y1 = rank_box
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    debug_lines.append(f"[bbox fallback] rank_bbox_raw=({x0},{y0},{x1},{y1}) size={width}x{height}")
    candidates = (
        ("below_rank", x0 - width, y1, x1 + width * 2, y1 + height * 3),
        ("rank_and_below", x0 - width, y0, x1 + width * 2, y1 + height * 3),
        ("wide_corner", x0 - width, y0, x1 + width * 4, y1 + height * 5),
        ("tight_rank", x0 - max(2, width // 2), y0 - max(2, height // 2), x1 + width, y1 + height),
    )
    for label, rx0, ry0, rx1, ry1 in candidates:
        roi = _clip_roi(region_bgr, rx0, ry0, rx1, ry1)
        debug_lines.append(f"[bbox fallback] suit_roi {label} size={roi.shape[1]}x{roi.shape[0]} px")
        if roi.size == 0:
            debug_lines.append(f"[bbox fallback] suit_roi {label} SKIPPED - empty after clipping")
            continue
        suit, suit_debug_lines = detect_suit_from_card_image_with_debug(roi)
        debug_lines.extend(f"[bbox fallback] suit_roi {label} {entry}" for entry in suit_debug_lines)
        debug_lines.append(f"[bbox fallback] suit_roi {label} result={suit or 'None'}")
        if suit is not None:
            return suit, tuple(debug_lines)
    return None, tuple(debug_lines)


def _scaled_bbox_bounds(
    bbox: tuple[tuple[int, int], ...],
    scale: float,
    image_shape: tuple[int, ...],
) -> tuple[int, int, int, int] | None:
    if not bbox:
        return None
    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    raw_x0 = int(min(xs) / scale)
    raw_y0 = int(min(ys) / scale)
    raw_x1 = int(max(xs) / scale)
    raw_y1 = int(max(ys) / scale)
    height, width = image_shape[:2]
    x0 = max(0, min(width, raw_x0))
    y0 = max(0, min(height, raw_y0))
    x1 = max(0, min(width, raw_x1))
    y1 = max(0, min(height, raw_y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _clip_roi(
    image: np.ndarray[Any, Any],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> np.ndarray[Any, Any]:
    height, width = image.shape[:2]
    left = max(0, min(width, int(x0)))
    top = max(0, min(height, int(y0)))
    right = max(0, min(width, int(x1)))
    bottom = max(0, min(height, int(y1)))
    if right <= left or bottom <= top:
        return image[0:0, 0:0]
    return image[top:bottom, left:right]


def is_probably_card_back(card_bgr: np.ndarray[Any, Any]) -> bool:
    """Detect Torn card backs so unrevealed board cards are ignored."""

    score, _white_ratio, _dark_ratio = card_back_score(card_bgr)
    return score >= 0.80


def card_back_score(card_bgr: np.ndarray[Any, Any]) -> tuple[float, float, float]:
    """Return card-back score plus supporting white/dark ratios."""

    import cv2

    if card_bgr.size == 0:
        return 1.0, 0.0, 1.0
    hsv = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2HSV)
    white_pixels = int(cv2.inRange(hsv, (0, 0, 160), (180, 65, 255)).sum() // 255)
    card_area = card_bgr.shape[0] * card_bgr.shape[1]
    white_ratio = white_pixels / max(card_area, 1)
    gray = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2GRAY)
    dark_pixels = int(cv2.inRange(gray, 0, 95).sum() // 255)
    dark_ratio = dark_pixels / max(card_area, 1)
    # Face-up cards have a large white field and rank/suit glyphs. Card backs
    # are patterned grey/green and become edge-heavy after thresholding.
    low_white_score = max(0.0, (0.45 - white_ratio) / 0.45)
    high_dark_score = max(0.0, (dark_ratio - 0.45) / 0.55)
    return max(low_white_score, high_dark_score), white_ratio, dark_ratio


def is_probably_folded_hero_region(region_bgr: np.ndarray[Any, Any]) -> bool:
    """Detect the greyed/line-through folded hero state shown by Torn."""

    _is_folded, _debug_lines = folded_hero_debug(region_bgr)
    return _is_folded


def folded_hero_debug(region_bgr: np.ndarray[Any, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return folded-state decision plus debug values."""

    import cv2

    if region_bgr.size == 0:
        return False, ("[hero folded guard] region empty; not folded",)
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    low_saturation_ratio = float(np.mean(saturation < 45))
    dim_ratio = float(np.mean(value < 150))
    upper = region_bgr[: max(1, int(region_bgr.shape[0] * 0.35))]
    upper_gray = cv2.cvtColor(upper, cv2.COLOR_BGR2GRAY)
    row_darkness = np.mean(upper_gray < 120, axis=1)
    has_long_horizontal_overlay = bool(np.any(row_darkness > 0.55))
    is_folded = (low_saturation_ratio > 0.55 and dim_ratio > 0.35) or has_long_horizontal_overlay
    return is_folded, (
        "[hero folded guard] "
        f"folded={is_folded} low_saturation_ratio={low_saturation_ratio:.3f} "
        f"dim_ratio={dim_ratio:.3f} has_long_horizontal_overlay={has_long_horizontal_overlay}",
    )


def find_card_face_crops(region_bgr: np.ndarray[Any, Any]) -> tuple[np.ndarray[Any, Any], ...]:
    """Find likely face-up white card rectangles in a hero/board region."""

    crops, _debug_lines = find_card_face_crops_with_debug(region_bgr)
    return crops


def find_card_face_crops_with_debug(region_bgr: np.ndarray[Any, Any]) -> tuple[tuple[np.ndarray[Any, Any], ...], tuple[str, ...]]:
    """Find likely face-up white card rectangles and explain every filter."""

    import cv2

    if region_bgr.size == 0:
        return (), ("[detector] SKIPPED - region image is empty",)
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(hsv, (0, 0, 130), (180, 80, 255))
    kernel = np.ones((3, 3), dtype=np.uint8)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hierarchy = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    debug_lines: list[str] = [
        f"[detector] region_size={region_bgr.shape[1]}x{region_bgr.shape[0]} px raw_contours={len(contours)}"
    ]
    region_area = region_bgr.shape[0] * region_bgr.shape[1]
    min_area = max(180, region_area * 0.015)
    for contour_index, contour in enumerate(contours):
        x, y, width, height = cv2.boundingRect(contour)
        area = width * height
        debug_lines.append(
            f"[contour_{contour_index}] bbox=({x},{y},{width},{height}) size={width}x{height} area={area}"
        )
        if area < min_area:
            debug_lines.append(
                f"[contour_{contour_index}] SKIPPED - image too small/low area "
                f"(area={area:.1f}, min={min_area:.1f})"
            )
            continue
        if height < 24 or width < 16:
            debug_lines.append(
                f"[contour_{contour_index}] SKIPPED - image too small "
                f"({width}x{height} px, min=16x24 px)"
            )
            continue
        aspect = width / max(height, 1)
        if not 0.35 <= aspect <= 0.95:
            debug_lines.append(
                f"[contour_{contour_index}] SKIPPED - failed card aspect filter "
                f"(aspect={aspect:.3f}, allowed=0.35..0.95)"
            )
            continue
        boxes.append((x, y, width, height))
        debug_lines.append(f"[contour_{contour_index}] accepted candidate")
    merged = _merge_overlapping_boxes(boxes)
    debug_lines.append(f"[detector] candidate_boxes={len(boxes)} merged_boxes={len(merged)}")
    crops: list[tuple[int, np.ndarray[Any, Any]]] = []
    for crop_index, (x, y, width, height) in enumerate(merged):
        crop = region_bgr[y : y + height, x : x + width]
        debug_lines.append(f"[crop_{crop_index}] bbox=({x},{y},{width},{height}) size={width}x{height} px")
        back_score, white_ratio, dark_ratio = card_back_score(crop)
        if back_score >= 0.80:
            debug_lines.append(
                f"[crop_{crop_index}] SKIPPED - failed back-card filter "
                f"(score={back_score:.3f}, threshold=0.800, white_ratio={white_ratio:.3f}, dark_ratio={dark_ratio:.3f})"
            )
            continue
        debug_lines.append(
            f"[crop_{crop_index}] accepted face-up card "
            f"(back_score={back_score:.3f}, white_ratio={white_ratio:.3f}, dark_ratio={dark_ratio:.3f})"
        )
        crops.append((x, crop))
    return tuple(crop for _x, crop in sorted(crops, key=lambda item: item[0])), tuple(debug_lines)


def _merge_overlapping_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda item: item[0]):
        x, y, width, height = box
        if not merged:
            merged.append(box)
            continue
        last_x, last_y, last_width, last_height = merged[-1]
        horizontal_overlap = min(last_x + last_width, x + width) - max(last_x, x)
        if horizontal_overlap > 0:
            x1 = min(last_x, x)
            y1 = min(last_y, y)
            x2 = max(last_x + last_width, x + width)
            y2 = max(last_y + last_height, y + height)
            merged[-1] = (x1, y1, x2 - x1, y2 - y1)
        else:
            merged.append(box)
    return merged


def read_card_rank_from_crop(card_bgr: np.ndarray[Any, Any], ocr: EasyOCREngine, scale: float) -> str | None:
    """OCR a card rank using multiple corner crops and threshold variants."""

    rank, _debug_lines = read_card_rank_from_crop_with_debug(card_bgr, ocr, scale=scale, crop_label="card")
    return rank


def read_card_rank_from_crop_with_debug(
    card_bgr: np.ndarray[Any, Any],
    ocr: EasyOCREngine,
    scale: float,
    crop_label: str,
) -> tuple[str | None, tuple[str, ...]]:
    """OCR a card rank and return raw EasyOCR diagnostics for every variant."""

    if card_bgr.size == 0:
        return None, (f"[{crop_label}] empty card crop",)
    height, width = card_bgr.shape[:2]
    crop_specs = (
        (0.00, 0.00, 0.45, 0.36),
        (0.00, 0.00, 0.55, 0.45),
        (0.00, 0.00, 0.70, 0.32),
    )
    debug_lines: list[str] = []
    for crop_index, (x0, y0, x1, y1) in enumerate(crop_specs):
        crop = card_bgr[int(height * y0) : max(1, int(height * y1)), int(width * x0) : max(1, int(width * x1))]
        debug_lines.append(
            f"[{crop_label}.rank_crop_{crop_index}] extracted size={crop.shape[1]}x{crop.shape[0]} px "
            f"from card size={width}x{height} px"
        )
        variants = (
            ("adaptive_dark_on_light", preprocess_card_region(crop, scale=scale)),
            ("simple_dark_on_light", _preprocess_rank_light(crop, scale=scale)),
        )
        for variant_name, variant in variants:
            raw_lines = ocr.read_raw(variant, allowlist=CARD_RANK_ALLOWLIST)
            debug_lines.extend(
                format_raw_ocr_debug_lines(
                    f"{crop_label}.rank_crop_{crop_index}.{variant_name}",
                    raw_lines,
                    allowlist=CARD_RANK_ALLOWLIST,
                )
            )
            for line in raw_lines:
                if line.confidence < 0.15:
                    continue
                rank = normalize_card_rank(line.text)
                if rank is not None:
                    return rank, tuple(debug_lines)
    return None, tuple(debug_lines)


def _preprocess_rank_light(frame: np.ndarray[Any, Any], scale: float) -> np.ndarray[Any, np.dtype[np.uint8]]:
    import cv2

    resized = cv2.resize(frame, None, fx=max(scale, 1.0), fy=max(scale, 1.0), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(4, 4)).apply(gray)
    blurred = cv2.GaussianBlur(clahe, (3, 3), 0)
    _threshold, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return cv2.cvtColor(_ensure_dark_text_on_light(binary), cv2.COLOR_GRAY2BGR)


def _ensure_dark_text_on_light(gray: np.ndarray[Any, Any]) -> np.ndarray[Any, np.dtype[np.uint8]]:
    import cv2

    if float(np.mean(gray)) < 127.0:
        return cv2.bitwise_not(gray)
    return gray


def detect_cards_from_region(
    region_bgr: np.ndarray[Any, Any],
    ocr: EasyOCREngine,
    scale: float,
    ignore_folded: bool = False,
    fallback_ocr_lines: tuple[OCRLine, ...] = (),
    fallback_ocr_scale: float | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if ignore_folded and is_probably_folded_hero_region(region_bgr):
        return (), ("[detector] folded/greyed hero region detected; ignoring hero cards",)
    cards: list[str] = []
    seen: set[str] = set()
    debug_lines: list[str] = []
    crops, crop_debug_lines = find_card_face_crops_with_debug(region_bgr)
    debug_lines.extend(crop_debug_lines)
    debug_lines.append(f"[detector] face_up_card_crops={len(crops)}")
    if not crops and fallback_ocr_lines:
        fallback_cards, fallback_debug_lines = detect_cards_from_ocr_bboxes(
            region_bgr,
            fallback_ocr_lines,
            ocr_scale=fallback_ocr_scale or scale,
        )
        debug_lines.extend(fallback_debug_lines)
        return fallback_cards, tuple(debug_lines)
    if not crops:
        debug_lines.append("[bbox fallback] SKIPPED - no fallback OCR lines available")
        return (), tuple(debug_lines)
    for crop_index, crop in enumerate(crops):
        rank, rank_debug_lines = read_card_rank_from_crop_with_debug(
            crop,
            ocr,
            scale=scale,
            crop_label=f"card_{crop_index}",
        )
        debug_lines.extend(rank_debug_lines)
        suit, suit_debug_lines = detect_suit_from_card_image_with_debug(crop)
        debug_lines.extend(f"[card_{crop_index}] {entry}" for entry in suit_debug_lines)
        debug_lines.append(f"[card_{crop_index}.result] rank={rank or 'None'} suit={suit or 'None'}")
        if rank is None or suit is None:
            continue
        card = f"{rank}{suit}"
        if card not in seen:
            cards.append(card)
            seen.add(card)
    return tuple(cards), tuple(debug_lines)


def detect_cards_from_ocr_bboxes(
    region_bgr: np.ndarray[Any, Any],
    ocr_lines: tuple[OCRLine, ...],
    ocr_scale: float,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Build cards directly from EasyOCR rank bboxes when contour detection fails."""

    debug_lines: list[str] = [
        f"[bbox fallback] ENTERED raw_ocr_lines={len(ocr_lines)} ocr_scale={ocr_scale:.3f}"
    ]
    candidates: list[tuple[int, str, str, float]] = []
    seen_locations: set[tuple[str, int, int]] = set()
    for line_index, line in enumerate(ocr_lines):
        rank = normalize_card_rank(line.text)
        debug_lines.append(
            f"[bbox fallback] raw_line_{line_index} text={line.text!r} "
            f"confidence={line.confidence:.4f} bbox={line.bbox} rank={rank or 'None'}"
        )
        if rank is None:
            debug_lines.append(f"[bbox fallback] raw_line_{line_index} SKIPPED - not a valid rank")
            continue
        bounds = _scaled_bbox_bounds(line.bbox, scale=max(ocr_scale, 1.0), image_shape=region_bgr.shape)
        if bounds is None:
            debug_lines.append(f"[bbox fallback] raw_line_{line_index} SKIPPED - invalid bbox after scaling")
            continue
        x0, y0, x1, y1 = bounds
        location_key = (rank, x0 // 12, y0 // 12)
        if location_key in seen_locations:
            debug_lines.append(f"[bbox fallback] raw_line_{line_index} SKIPPED - duplicate nearby rank")
            continue
        suit, suit_debug_lines = detect_suit_near_rank_bbox(region_bgr, line.bbox, ocr_scale=ocr_scale)
        debug_lines.extend(f"[bbox fallback] raw_line_{line_index} {entry}" for entry in suit_debug_lines)
        if suit is None:
            debug_lines.append(f"[bbox fallback] raw_line_{line_index} SKIPPED - suit not detected near bbox")
            continue
        card = f"{rank}{suit}"
        seen_locations.add(location_key)
        candidates.append((x0, card, rank, line.confidence))
        debug_lines.append(f"[bbox fallback] raw_line_{line_index} ACCEPTED card={card} x={x0}")
    cards: list[str] = []
    seen_cards: set[str] = set()
    for _x, card, _rank, _confidence in sorted(candidates, key=lambda item: item[0]):
        if card in seen_cards:
            continue
        cards.append(card)
        seen_cards.add(card)
    debug_lines.append(f"[bbox fallback] detected_cards={' '.join(cards) if cards else '<none>'}")
    return tuple(cards), tuple(debug_lines)


def preprocess_card_region(
    frame: np.ndarray[Any, Any],
    scale: float = 3.0,
) -> np.ndarray[Any, np.dtype[np.uint8]]:
    """Prepare card-image crops for OCR without crushing dark-theme shadows.

    EasyOCR tends to prefer dark glyphs on light backgrounds. Dark-mode Torn
    cards often render light text with subtle shadows, so hard binary
    thresholding can erase the right card's rank. This path keeps grayscale
    detail, boosts local contrast with CLAHE, and only inverts when needed.
    """

    import cv2

    if frame.size == 0:
        raise ValueError("Cannot preprocess an empty card region.")
    scale = max(scale, 1.0)
    resized = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=35, sigmaSpace=35)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    normalized = _ensure_dark_text_on_light(clahe)
    sharpen_kernel = np.array([[0, -0.35, 0], [-0.35, 2.4, -0.35], [0, -0.35, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(normalized, -1, sharpen_kernel)
    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


class CardRegionDebugger:
    """Capture calibrated hero/board card regions and save OCR diagnostics."""

    REGION_ATTRS = (
        ("hero_cards_region", "Your hand"),
        ("board_cards_region", "Board"),
    )

    def __init__(self, config: OCRConfig) -> None:
        self.config = config
        self.output_dir = Path(config.debug_card_regions_dir)
        self.regions = self._load_regions(config.calibrated_regions_path)
        self.last_saved_at: dict[str, float] = {}
        self.last_error: str | None = None
        self.last_detected: dict[str, tuple[str, ...]] = {}
        self._log_configured_regions()

    @property
    def enabled(self) -> bool:
        return self.config.debug_card_regions and bool(self.regions)

    def write_stability_skip(self, capture: ScreenCapture, frame_id: int, reason: str) -> None:
        if not self.enabled:
            return
        interval = max(self.config.debug_card_regions_interval_sec, 0.1)
        key = "stability_skip"
        if time.monotonic() - self.last_saved_at.get(key, 0.0) < interval:
            return
        for region_name, _label in self.REGION_ATTRS:
            region = self.regions.get(region_name)
            if region is None:
                continue
            raw = capture.grab_region(region)
            prefix = self._debug_prefix(region_name, frame_id)
            header_lines = self._debug_header(frame_id, region_name, raw)
            self._write_debug_text(
                prefix,
                (
                    *header_lines,
                    f"[frame stability] SKIPPED - stable-frame debounce has not passed (reason={reason})",
                ),
            )
            self._save_raw_debug_image(prefix, raw)
        self.last_saved_at[key] = time.monotonic()

    def capture_and_read(
        self,
        capture: ScreenCapture,
        ocr: EasyOCREngine,
        frame_id: int,
    ) -> tuple[OCRLine, ...]:
        debug_log("card_detector called frame=%s", frame_id)
        if not self.enabled:
            debug_log(
                "card_detector disabled: debug_card_regions=%s loaded_regions=%s",
                self.config.debug_card_regions,
                sorted(self.regions),
            )
            return ()
        diagnostic_lines: list[OCRLine] = []
        for region_name, label in self.REGION_ATTRS:
            interval = self._interval_for_region(region_name)
            last_saved_at = self.last_saved_at.get(region_name, 0.0)
            should_process = time.monotonic() - last_saved_at >= interval
            if not should_process:
                debug_log("card_detector throttled frame=%s region=%s interval=%.2fs", frame_id, region_name, interval)
                continue
            region = self.regions.get(region_name)
            if region is None:
                debug_log("card_detector region missing frame=%s region=%s", frame_id, region_name)
                continue
            raw = capture.grab_region(region)
            debug_log(
                "card_detector crop frame=%s region=%s size=%sx%s px",
                frame_id,
                region_name,
                raw.shape[1],
                raw.shape[0],
            )
            prefix = self._debug_prefix(region_name, frame_id)
            header_lines = self._debug_header(frame_id, region_name, raw)
            self._write_debug_text(prefix, header_lines)
            try:
                if raw.size == 0 or raw.shape[0] == 0 or raw.shape[1] == 0:
                    zero_lines = (*header_lines, "[detector] SKIPPED - captured region is 0x0 pixels")
                    self._write_debug_text(prefix, zero_lines)
                    debug_log("card_detector skipped frame=%s region=%s: 0x0 crop", frame_id, region_name)
                    continue
                processed = preprocess_card_region(raw, scale=self.config.card_ocr_scale)
                region_raw_ocr = ocr.read_raw(processed, allowlist=self.config.card_ocr_allowlist)
                detected_cards, debug_lines_for_file = detect_cards_from_region(
                    raw,
                    ocr,
                    scale=self.config.card_ocr_scale,
                    ignore_folded=False,
                    fallback_ocr_lines=region_raw_ocr,
                    fallback_ocr_scale=self.config.card_ocr_scale,
                )
                expected_cards = 2 if region_name == "hero_cards_region" else 3
                max_cards = 2 if region_name == "hero_cards_region" else 5
                all_debug_lines = (
                    *header_lines,
                    f"[preprocess] region_preprocessed size={processed.shape[1]}x{processed.shape[0]} px",
                    *format_raw_ocr_debug_lines(
                        f"{region_name}.region_preprocessed",
                        region_raw_ocr,
                        allowlist=self.config.card_ocr_allowlist,
                    ),
                    *self._folded_gate_debug_lines(region_name),
                    *debug_lines_for_file,
                    f"[detected_cards] {' '.join(detected_cards) if detected_cards else '<none>'}",
                )
                if expected_cards <= len(detected_cards) <= max_cards and detected_cards != self.last_detected.get(region_name):
                    diagnostic_text = " ".join(detected_cards)
                    diagnostic_lines.append(
                        OCRLine(text=f"{label}: {diagnostic_text}", confidence=1.0)
                    )
                    self.last_detected[region_name] = detected_cards
                self._save_debug_images(prefix, raw, processed, all_debug_lines)
            except Exception as exc:  # noqa: BLE001 - debug logging must survive detector failures
                error_lines = (*header_lines, f"[error] {type(exc).__name__}: {exc}")
                self._write_debug_text(prefix, error_lines)
                self.last_error = f"{region_name} card debug failed: {type(exc).__name__}: {exc}"
                continue
            self.last_saved_at[region_name] = time.monotonic()
        return tuple(diagnostic_lines)

    def _interval_for_region(self, region_name: str) -> float:
        if region_name == "hero_cards_region":
            return max(self.config.hero_cards_interval_sec, 0.0)
        return max(self.config.debug_card_regions_interval_sec, 0.1)

    @staticmethod
    def _folded_gate_debug_lines(region_name: str) -> tuple[str, ...]:
        if region_name != "hero_cards_region":
            return ()
        return (
            "[hero folded guard] disabled - Torn dark/inverted card theme can look greyed; attempting OCR anyway",
        )

    def _debug_prefix(self, region_name: str, frame_id: int) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir / f"frame_{frame_id:06d}_{region_name}"

    def _debug_header(self, frame_id: int, region_name: str, raw: np.ndarray[Any, Any]) -> tuple[str, ...]:
        current_label = "hero" if region_name == "hero_cards_region" else "board"
        lines = [
            f"=== card detector entered for frame {frame_id:06d} region={region_name} ===",
            f"{current_label} captured crop size: {raw.shape[1]}x{raw.shape[0]} px",
        ]
        for configured_region_name, label in (
            ("hero_cards_region", "hero"),
            ("board_cards_region", "board"),
        ):
            configured = self.regions.get(configured_region_name)
            if configured is None:
                lines.append(f"{label} region size: <missing from calibrated regions>")
            else:
                lines.append(f"{label} region size: {configured.width}x{configured.height} px")
        return tuple(lines)

    def _save_debug_images(
        self,
        prefix: Path,
        raw: np.ndarray[Any, Any],
        processed: np.ndarray[Any, Any],
        debug_lines: tuple[str, ...],
    ) -> None:
        import cv2

        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_raw.png")), raw)
        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_preprocessed.png")), processed)
        self._write_debug_text(prefix, debug_lines)

    def _save_raw_debug_image(self, prefix: Path, raw: np.ndarray[Any, Any]) -> None:
        import cv2

        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_raw.png")), raw)

    def _write_debug_text(self, prefix: Path, debug_lines: tuple[str, ...]) -> None:
        with prefix.with_name(f"{prefix.name}_ocr.txt").open("w", encoding="utf-8") as fp:
            for line in debug_lines:
                fp.write(f"{line}\n")

    def _load_regions(self, path: str | None) -> dict[str, Any]:
        regions: dict[str, Any] = {}
        if not path:
            regions = {}
        else:
            regions_path = Path(path)
            if not regions_path.exists():
                self.last_error = f"Calibrated regions file not found: {regions_path}"
            else:
                try:
                    regions = RegionsConfig.load(regions_path).as_dict()
                except (OSError, ValueError) as exc:
                    self.last_error = f"Unable to load calibrated regions: {exc}"
                    regions = {}
        if self.config.hero_cards_region is not None:
            regions["hero_cards_region"] = self.config.hero_cards_region
        if self.config.board_cards_region is not None:
            regions["board_cards_region"] = self.config.board_cards_region
        return {
            region_name: regions[region_name]
            for region_name, _label in self.REGION_ATTRS
            if region_name in regions
        }

    def _log_configured_regions(self) -> None:
        for region_name, _label in self.REGION_ATTRS:
            region = self.regions.get(region_name)
            if region is None:
                debug_log("configured %s: <missing>", region_name)
                continue
            debug_log(
                "configured %s: left=%s top=%s width=%s height=%s",
                region_name,
                region.left,
                region.top,
                region.width,
                region.height,
            )


class OCRWorker(threading.Thread):
    """Capture, debounce, and OCR frames without blocking Tkinter."""

    def __init__(self, app_config: AppConfig, output_queue: queue.Queue[OCRBatch]) -> None:
        write_startup_log("OCRWorker.__init__ called")
        debug_log("OCRWorker.__init__ called")
        super().__init__(name="torn-ocr-worker", daemon=True)
        self.app_config = app_config
        self.output_queue = output_queue
        self.stop_event = threading.Event()
        self.last_error: str | None = None
        self.last_debounce_reason = "not started"
        self._frame_id = 0
        self._capture_frame_id = 0

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        write_startup_log("OCRWorker.run() started")
        debug_log("OCRWorker.run() started")
        capture: ScreenCapture | None = None
        try:
            capture = ScreenCapture(self.app_config.capture)
            debouncer = StableFrameDebouncer(self.app_config.debounce)
            ocr = EasyOCREngine(self.app_config.ocr)
            card_debugger = CardRegionDebugger(self.app_config.ocr)
            min_interval = 1.0 / max(self.app_config.capture.fps_limit, 1.0)
            try:
                with capture:
                    while not self.stop_event.is_set():
                        started = time.monotonic()
                        try:
                            frame = capture.grab()
                            self._capture_frame_id += 1
                            card_lines = card_debugger.capture_and_read(capture, ocr, self._capture_frame_id)
                            debounce = debouncer.update(frame)
                            self.last_debounce_reason = debounce.reason
                            if debounce.is_stable:
                                lines = ocr.read(frame)
                                self._frame_id += 1
                                self._put_latest(
                                    OCRBatch(lines=lines + card_lines, frame_id=self._frame_id, captured_at=time.time())
                                )
                                if card_debugger.last_error:
                                    self.last_error = card_debugger.last_error
                            else:
                                debug_log(
                                    "frame %s dropped: reason=%s stable_count=%s motion_score=%.3f",
                                    self._capture_frame_id,
                                    debounce.reason,
                                    debounce.stable_count,
                                    debounce.motion_score,
                                )
                                if card_lines:
                                    self._put_latest(
                                        OCRBatch(
                                            lines=card_lines,
                                            frame_id=self._capture_frame_id,
                                            captured_at=time.time(),
                                        )
                                    )
                        except Exception as exc:  # noqa: BLE001 - worker must not kill the UI loop
                            self.last_error = f"{type(exc).__name__}: {exc}"
                            exception_log("OCRWorker loop exception: %s", exc)
                            time.sleep(0.25)
                        elapsed = time.monotonic() - started
                        if elapsed < min_interval:
                            self.stop_event.wait(min_interval - elapsed)
            finally:
                capture.close()
        except Exception as exc:  # noqa: BLE001 - daemon thread must expose startup crashes
            self.last_error = f"{type(exc).__name__}: {exc}"
            exception_log("OCRWorker.run() CRASHED: %s", exc)
        finally:
            if capture is not None:
                capture.close()

    def _put_latest(self, batch: OCRBatch) -> None:
        while True:
            try:
                self.output_queue.put_nowait(batch)
                return
            except queue.Full:
                try:
                    self.output_queue.get_nowait()
                except queue.Empty:
                    return
