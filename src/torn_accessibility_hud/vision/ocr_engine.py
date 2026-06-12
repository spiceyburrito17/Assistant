"""CUDA-configured EasyOCR processing and background worker."""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

import numpy as np

from ..config import AppConfig, OCRConfig
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

    def read(self, frame: np.ndarray[Any, Any]) -> tuple[OCRLine, ...]:
        results = self.reader.readtext(frame, detail=1, paragraph=self.config.paragraph)
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
                            self._put_latest(
                                OCRBatch(lines=lines, frame_id=self._frame_id, captured_at=time.time())
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
