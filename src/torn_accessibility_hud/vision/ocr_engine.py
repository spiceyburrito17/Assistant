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
        kwargs: dict[str, Any] = {"detail": 1, "paragraph": self.config.paragraph}
        if allowlist:
            kwargs["allowlist"] = allowlist
        results = self.reader.readtext(frame, **kwargs)
        lines: list[OCRLine] = []
        confidence_floor = self.config.min_confidence if min_confidence is None else min_confidence
        for result in results:
            if len(result) < 3:
                continue
            bbox_raw, text, confidence = result[0], str(result[1]), float(result[2])
            if confidence < confidence_floor:
                continue
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

    import cv2

    if card_bgr.size == 0:
        return True
    hsv = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2HSV)
    white_pixels = int(cv2.inRange(hsv, (0, 0, 160), (180, 65, 255)).sum() // 255)
    card_area = card_bgr.shape[0] * card_bgr.shape[1]
    white_ratio = white_pixels / max(card_area, 1)
    gray = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2GRAY)
    dark_pixels = int(cv2.inRange(gray, 0, 95).sum() // 255)
    # Face-up cards have a large white field and rank/suit glyphs. Card backs
    # are patterned grey/green and become edge-heavy after thresholding.
    return white_ratio < 0.45 or dark_pixels / max(card_area, 1) > 0.45


def is_probably_folded_hero_region(region_bgr: np.ndarray[Any, Any]) -> bool:
    """Detect the greyed/line-through folded hero state shown by Torn."""

    import cv2

    if region_bgr.size == 0:
        return False
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    low_saturation_ratio = float(np.mean(saturation < 45))
    dim_ratio = float(np.mean(value < 150))
    upper = region_bgr[: max(1, int(region_bgr.shape[0] * 0.35))]
    upper_gray = cv2.cvtColor(upper, cv2.COLOR_BGR2GRAY)
    row_darkness = np.mean(upper_gray < 120, axis=1)
    has_long_horizontal_overlay = bool(np.any(row_darkness > 0.55))
    return (low_saturation_ratio > 0.55 and dim_ratio > 0.35) or has_long_horizontal_overlay


def find_card_face_crops(region_bgr: np.ndarray[Any, Any]) -> tuple[np.ndarray[Any, Any], ...]:
    """Find likely face-up white card rectangles in a hero/board region."""

    import cv2

    if region_bgr.size == 0:
        return ()
    hsv = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(hsv, (0, 0, 130), (180, 80, 255))
    kernel = np.ones((3, 3), dtype=np.uint8)
    white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _hierarchy = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    region_area = region_bgr.shape[0] * region_bgr.shape[1]
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = width * height
        if area < max(180, region_area * 0.015):
            continue
        if height < 24 or width < 16:
            continue
        aspect = width / max(height, 1)
        if not 0.35 <= aspect <= 0.95:
            continue
        boxes.append((x, y, width, height))
    merged = _merge_overlapping_boxes(boxes)
    crops: list[tuple[int, np.ndarray[Any, Any]]] = []
    for x, y, width, height in merged:
        crop = region_bgr[y : y + height, x : x + width]
        if is_probably_card_back(crop):
            continue
        crops.append((x, crop))
    return tuple(crop for _x, crop in sorted(crops, key=lambda item: item[0]))


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

    if card_bgr.size == 0:
        return None
    height, width = card_bgr.shape[:2]
    crop_specs = (
        (0.00, 0.00, 0.45, 0.36),
        (0.00, 0.00, 0.55, 0.45),
        (0.00, 0.00, 0.70, 0.32),
    )
    for x0, y0, x1, y1 in crop_specs:
        crop = card_bgr[int(height * y0) : max(1, int(height * y1)), int(width * x0) : max(1, int(width * x1))]
        variants = (preprocess_card_region(crop, scale=scale), _preprocess_rank_light(crop, scale=scale))
        for variant in variants:
            for line in ocr.read(variant, allowlist="A23456789TJQK10", min_confidence=0.05):
                rank = normalize_card_rank(line.text)
                if rank is not None:
                    return rank
    return None


def _preprocess_rank_light(frame: np.ndarray[Any, Any], scale: float) -> np.ndarray[Any, np.dtype[np.uint8]]:
    import cv2

    resized = cv2.resize(frame, None, fx=max(scale, 1.0), fy=max(scale, 1.0), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    _threshold, binary = cv2.threshold(gray, 145, 255, cv2.THRESH_BINARY)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def detect_cards_from_region(
    region_bgr: np.ndarray[Any, Any],
    ocr: EasyOCREngine,
    scale: float,
    ignore_folded: bool = False,
) -> tuple[str, ...]:
    if ignore_folded and is_probably_folded_hero_region(region_bgr):
        return ()
    cards: list[str] = []
    seen: set[str] = set()
    for crop in find_card_face_crops(region_bgr):
        rank = read_card_rank_from_crop(crop, ocr, scale=scale)
        suit = detect_suit_from_card_image(crop)
        if rank is None or suit is None:
            continue
        card = f"{rank}{suit}"
        if card not in seen:
            cards.append(card)
            seen.add(card)
    return tuple(cards)


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
        self.last_saved_at = 0.0
        self.last_error: str | None = None
        self.last_detected: dict[str, tuple[str, ...]] = {}

    @property
    def enabled(self) -> bool:
        return self.config.debug_card_regions and bool(self.regions)

    def capture_and_read(
        self,
        capture: ScreenCapture,
        ocr: EasyOCREngine,
        frame_id: int,
    ) -> tuple[OCRLine, ...]:
        if not self.enabled:
            return ()
        interval = max(self.config.debug_card_regions_interval_sec, 0.1)
        should_process = time.monotonic() - self.last_saved_at >= interval
        if not should_process:
            return ()
        diagnostic_lines: list[OCRLine] = []
        for region_name, label in self.REGION_ATTRS:
            region = self.regions.get(region_name)
            if region is None:
                continue
            raw = capture.grab_region(region)
            processed = preprocess_card_region(raw, scale=self.config.card_ocr_scale)
            detected_cards = detect_cards_from_region(
                raw,
                ocr,
                scale=self.config.card_ocr_scale,
                ignore_folded=region_name == "hero_cards_region",
            )
            expected_cards = 2 if region_name == "hero_cards_region" else 3
            max_cards = 2 if region_name == "hero_cards_region" else 5
            diagnostic_lines_for_file = tuple(
                OCRLine(text=card, confidence=1.0) for card in detected_cards
            )
            if expected_cards <= len(detected_cards) <= max_cards and detected_cards != self.last_detected.get(region_name):
                diagnostic_text = " ".join(detected_cards)
                diagnostic_lines.append(
                    OCRLine(text=f"{label}: {diagnostic_text}", confidence=1.0)
                )
                self.last_detected[region_name] = detected_cards
            self._save_debug_images(region_name, frame_id, raw, processed, diagnostic_lines_for_file)
        self.last_saved_at = time.monotonic()
        return tuple(diagnostic_lines)

    def _save_debug_images(
        self,
        region_name: str,
        frame_id: int,
        raw: np.ndarray[Any, Any],
        processed: np.ndarray[Any, Any],
        lines: tuple[OCRLine, ...],
    ) -> None:
        import cv2

        self.output_dir.mkdir(parents=True, exist_ok=True)
        prefix = self.output_dir / f"frame_{frame_id:06d}_{region_name}"
        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_raw.png")), raw)
        cv2.imwrite(str(prefix.with_name(f"{prefix.name}_preprocessed.png")), processed)
        with prefix.with_name(f"{prefix.name}_ocr.txt").open("w", encoding="utf-8") as fp:
            for line in lines:
                fp.write(f"{line.confidence:.3f}\t{line.text}\n")

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
                        debounce = debouncer.update(frame)
                        self.last_debounce_reason = debounce.reason
                        if debounce.is_stable:
                            lines = ocr.read(frame)
                            self._frame_id += 1
                            card_lines = card_debugger.capture_and_read(capture, ocr, self._frame_id)
                            self._put_latest(
                                OCRBatch(lines=lines + card_lines, frame_id=self._frame_id, captured_at=time.time())
                            )
                            if card_debugger.last_error:
                                self.last_error = card_debugger.last_error
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
