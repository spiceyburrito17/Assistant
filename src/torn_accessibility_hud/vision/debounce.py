"""Stable-frame debouncing for animated game UI regions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..config import DebounceConfig


@dataclass(frozen=True)
class DebounceResult:
    is_stable: bool
    reason: str
    stable_count: int
    motion_score: float


class StableFrameDebouncer:
    """Require multiple visually stable frames before OCR is allowed.

    Flashing buttons, scrolling transitions, and overlay animations cause high
    inter-frame deltas. This class only releases frames once the downsampled
    grayscale signature remains within a small mean-delta threshold for the
    configured number of consecutive frames.
    """

    def __init__(self, config: DebounceConfig | None = None) -> None:
        self.config = config or DebounceConfig()
        self._last_signature: np.ndarray[Any, np.dtype[np.float32]] | None = None
        self._stable_count = 0

    def reset(self) -> None:
        self._last_signature = None
        self._stable_count = 0

    def update(self, frame: np.ndarray[Any, Any]) -> DebounceResult:
        signature = self._signature(frame)
        luma = float(signature.mean())
        variance = float(signature.var())
        if luma < self.config.min_luma:
            self.reset()
            return DebounceResult(False, "frame too dark", 0, 999.0)
        if luma > self.config.max_luma:
            self.reset()
            return DebounceResult(False, "frame too bright", 0, 999.0)
        if variance < self.config.min_variance:
            self.reset()
            return DebounceResult(False, "frame lacks readable contrast", 0, 999.0)

        if self._last_signature is None:
            self._last_signature = signature
            self._stable_count = 1
            return DebounceResult(False, "first frame", self._stable_count, 999.0)

        motion_score = float(np.mean(np.abs(signature - self._last_signature)))
        self._last_signature = signature
        if motion_score <= self.config.max_mean_delta:
            self._stable_count += 1
        else:
            self._stable_count = 1
            return DebounceResult(False, "motion detected", self._stable_count, motion_score)

        is_stable = self._stable_count >= self.config.stable_frames_required
        reason = "stable" if is_stable else "collecting stable frames"
        return DebounceResult(is_stable, reason, self._stable_count, motion_score)

    def _signature(self, frame: np.ndarray[Any, Any]) -> np.ndarray[Any, np.dtype[np.float32]]:
        if frame.ndim == 3 and frame.shape[2] >= 3:
            # BGR/RGB distinction does not matter for luma approximation here.
            gray = frame[:, :, :3].mean(axis=2)
        elif frame.ndim == 2:
            gray = frame
        else:
            raise ValueError(f"Unsupported frame shape for debounce: {frame.shape}")

        target_h = self.config.hash_height
        target_w = self.config.hash_width
        y_idx = np.linspace(0, gray.shape[0] - 1, target_h).astype(np.int32)
        x_idx = np.linspace(0, gray.shape[1] - 1, target_w).astype(np.int32)
        return gray[np.ix_(y_idx, x_idx)].astype(np.float32)
