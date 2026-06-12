"""CUDA-configured EasyOCR processing and background worker."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import AppConfig, OCRConfig, RegionsConfig
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
            import easyocr

            self._reader = easyocr.Reader(list(self.config.languages), gpu=self.config.gpu)
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

    import cv2

    if card_bgr.size == 0:
        return None
    sample = card_bgr[: max(1, int(card_bgr.shape[0] * 0.45)), : max(1, int(card_bgr.shape[1] * 0.45))]
    hsv = cv2.cvtColor(sample, cv2.COLOR_BGR2HSV)
    masks = {
        "h": cv2.inRange(hsv, (0, 70, 50), (12, 255, 255)) | cv2.inRange(hsv, (170, 70, 50), (180, 255, 255)),
        "d": cv2.inRange(hsv, (90, 70, 50), (130, 255, 255)),
        "c": cv2.inRange(hsv, (35, 45, 40), (85, 255, 255)),
    }
    scores = {suit: int(mask.sum() // 255) for suit, mask in masks.items()}
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    dark_score = int(cv2.inRange(gray, 0, 90).sum() // 255)
    scores["s"] = dark_score
    best_suit, best_score = max(scores.items(), key=lambda item: item[1])
    return best_suit if best_score >= 8 else None


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
    _threshold, binary = cv2.threshold(gray, 145, 255, cv2.THRESH_BINARY)
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
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if ignore_folded and is_probably_folded_hero_region(region_bgr):
        return (), ("[detector] folded/greyed hero region detected; ignoring hero cards",)
    cards: list[str] = []
    seen: set[str] = set()
    debug_lines: list[str] = []
    crops = find_card_face_crops(region_bgr)
    debug_lines.append(f"[detector] face_up_card_crops={len(crops)}")
    for crop_index, crop in enumerate(crops):
        rank, rank_debug_lines = read_card_rank_from_crop_with_debug(
            crop,
            ocr,
            scale=scale,
            crop_label=f"card_{crop_index}",
        )
        debug_lines.extend(rank_debug_lines)
        suit = detect_suit_from_card_image(crop)
        debug_lines.append(f"[card_{crop_index}.result] rank={rank or 'None'} suit={suit or 'None'}")
        if rank is None or suit is None:
            continue
        card = f"{rank}{suit}"
        if card not in seen:
            cards.append(card)
            seen.add(card)
    return tuple(cards), tuple(debug_lines)


def preprocess_card_region(
    frame: np.ndarray[Any, Any],
    scale: float = 3.0,
) -> np.ndarray[Any, np.dtype[np.uint8]]:
    """Prepare card-image crops for OCR.

    Poker cards are rendered as small images, not plain text. Upscaling,
    grayscale conversion, local contrast enhancement, and adaptive thresholding
    make ranks/suit glyphs stand out from textured table backgrounds before
    EasyOCR sees the crop.
    """

    import cv2

    if frame.size == 0:
        raise ValueError("Cannot preprocess an empty card region.")
    scale = max(scale, 1.0)
    resized = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    denoised = cv2.bilateralFilter(gray, d=5, sigmaColor=45, sigmaSpace=45)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(denoised)
    thresholded = cv2.adaptiveThreshold(
        clahe,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )
    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharpened = cv2.filter2D(thresholded, -1, sharpen_kernel)
    return cv2.cvtColor(_ensure_dark_text_on_light(sharpened), cv2.COLOR_GRAY2BGR)


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
        self.last_saved_at = 0.0
        self.last_error: str | None = None
        self.last_detected: dict[str, tuple[str, ...]] = {}

    @property
    def enabled(self) -> bool:
        return self.config.debug_card_regions and bool(self.regions)

    def write_stability_skip(self, capture: ScreenCapture, frame_id: int, reason: str) -> None:
        if not self.enabled:
            return
        interval = max(self.config.debug_card_regions_interval_sec, 0.1)
        if time.monotonic() - self.last_saved_at < interval:
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
        self.last_saved_at = time.monotonic()

    def capture_and_read(
        self,
        capture: ScreenCapture,
        ocr: EasyOCREngine,
        frame_id: int,
    ) -> tuple[OCRLine, ...]:
        print(f"[DEBUG] card_detector called frame={frame_id}", flush=True)
        if not self.enabled:
            print(
                "[DEBUG] card_detector disabled: "
                f"debug_card_regions={self.config.debug_card_regions} loaded_regions={sorted(self.regions)}",
                flush=True,
            )
            return ()
        interval = max(self.config.debug_card_regions_interval_sec, 0.1)
        should_process = time.monotonic() - self.last_saved_at >= interval
        if not should_process:
            print(f"[DEBUG] card_detector throttled frame={frame_id} interval={interval:.2f}s", flush=True)
            return ()
        diagnostic_lines: list[OCRLine] = []
        for region_name, label in self.REGION_ATTRS:
            region = self.regions.get(region_name)
            if region is None:
                print(f"[DEBUG] card_detector region missing frame={frame_id} region={region_name}", flush=True)
                continue
            raw = capture.grab_region(region)
            print(
                f"[DEBUG] card_detector crop frame={frame_id} region={region_name} "
                f"size={raw.shape[1]}x{raw.shape[0]} px",
                flush=True,
            )
            prefix = self._debug_prefix(region_name, frame_id)
            header_lines = self._debug_header(frame_id, region_name, raw)
            self._write_debug_text(prefix, header_lines)
            try:
                if raw.size == 0 or raw.shape[0] == 0 or raw.shape[1] == 0:
                    zero_lines = (*header_lines, "[detector] SKIPPED - captured region is 0x0 pixels")
                    self._write_debug_text(prefix, zero_lines)
                    print(
                        f"[DEBUG] card_detector skipped frame={frame_id} region={region_name}: 0x0 crop",
                        flush=True,
                    )
                    continue
                processed = preprocess_card_region(raw, scale=self.config.card_ocr_scale)
                region_raw_ocr = ocr.read_raw(processed, allowlist=self.config.card_ocr_allowlist)
                detected_cards, debug_lines_for_file = detect_cards_from_region(
                    raw,
                    ocr,
                    scale=self.config.card_ocr_scale,
                    ignore_folded=region_name == "hero_cards_region",
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
        self.last_saved_at = time.monotonic()
        return tuple(diagnostic_lines)

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
        if not path:
            return {}
        regions_path = Path(path)
        if not regions_path.exists():
            self.last_error = f"Calibrated regions file not found: {regions_path}"
            return {}
        try:
            regions = RegionsConfig.load(regions_path).as_dict()
        except (OSError, ValueError) as exc:
            self.last_error = f"Unable to load calibrated regions: {exc}"
            return {}
        return {
            region_name: regions[region_name]
            for region_name, _label in self.REGION_ATTRS
            if region_name in regions
        }


class OCRWorker(threading.Thread):
    """Capture, debounce, and OCR frames without blocking Tkinter."""

    def __init__(self, app_config: AppConfig, output_queue: queue.Queue[OCRBatch]) -> None:
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
                            print(
                                f"[DEBUG] frame {self._capture_frame_id} dropped: "
                                f"reason={debounce.reason} stable_count={debounce.stable_count} "
                                f"motion_score={debounce.motion_score:.3f}",
                                flush=True,
                            )
                            card_debugger.write_stability_skip(capture, self._capture_frame_id, debounce.reason)
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
                        time.sleep(0.25)
                    elapsed = time.monotonic() - started
                    if elapsed < min_interval:
                        self.stop_event.wait(min_interval - elapsed)
        finally:
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
