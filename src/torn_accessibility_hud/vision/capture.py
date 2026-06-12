"""MSS screen capture wrapper."""

from __future__ import annotations

from typing import Any

import numpy as np

from ..config import CaptureConfig
from ..models import ScreenRegion


class ScreenCapture:
    """Capture a configured screen region without touching the UI thread."""

    def __init__(self, config: CaptureConfig | None = None) -> None:
        self.config = config or CaptureConfig()
        self._mss: Any | None = None

    def __enter__(self) -> "ScreenCapture":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self._mss is None:
            import mss

            self._mss = mss.mss()

    def close(self) -> None:
        if self._mss is not None:
            self._mss.close()
            self._mss = None

    def grab(self) -> np.ndarray[Any, np.dtype[np.uint8]]:
        return self.grab_region(self.config.region)

    def grab_region(self, region: ScreenRegion) -> np.ndarray[Any, np.dtype[np.uint8]]:
        if self._mss is None:
            self.start()
        assert self._mss is not None
        frame = np.asarray(self._mss.grab(region.to_mss()), dtype=np.uint8)
        # MSS returns BGRA. EasyOCR/OpenCV accept BGR, so drop alpha.
        return frame[:, :, :3]
