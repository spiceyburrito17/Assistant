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

    def read(self, frame: np.ndarray[Any, Any], allowlist: str | None = None) -> tuple[OCRLine, ...]:
        kwargs: dict[str, Any] = {"detail": 1, "paragraph": self.config.paragraph}
        if allowlist:
            kwargs["allowlist"] = allowlist
        results = self.reader.readtext(frame, **kwargs)
        lines: list[OCRLine] = []
        for result in results:
            if len(result) < 3:
                continue
            bbox_raw, text, confidence = result[0], str(result[1]), float(result[2])
            if confidence < self.config.min_confidence:
                continue
            bbox = tuple((int(point[0]), int(point[1])) for point in bbox_raw)
            lines.append(OCRLine(text=text, confidence=confidence, bbox=bbox))
        return tuple(sorted(lines, key=lambda line: (line.bbox[0][1] if line.bbox else 0, line.bbox[0][0] if line.bbox else 0)))


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
            lines = ocr.read(processed, allowlist=self.config.card_ocr_allowlist)
            diagnostic_text = " ".join(line.text for line in lines).strip()
            if diagnostic_text:
                confidence = min((line.confidence for line in lines), default=0.0)
                diagnostic_lines.append(
                    OCRLine(text=f"{label}: {diagnostic_text}", confidence=max(confidence, self.config.min_confidence))
                )
            self._save_debug_images(region_name, frame_id, raw, processed, lines)
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
