import unittest

import numpy as np

from torn_accessibility_hud.config import DebounceConfig
from torn_accessibility_hud.vision.debounce import StableFrameDebouncer


class DebounceTests(unittest.TestCase):
    def test_requires_consecutive_stable_frames(self) -> None:
        config = DebounceConfig(
            stable_frames_required=3,
            max_mean_delta=1.0,
            hash_width=8,
            hash_height=8,
            min_luma=1.0,
            max_luma=254.0,
            min_variance=1.0,
        )
        debouncer = StableFrameDebouncer(config)
        frame = self._readable_frame()
        self.assertFalse(debouncer.update(frame).is_stable)
        self.assertFalse(debouncer.update(frame).is_stable)
        self.assertTrue(debouncer.update(frame).is_stable)

    def test_motion_resets_stability(self) -> None:
        config = DebounceConfig(
            stable_frames_required=2,
            max_mean_delta=1.0,
            hash_width=8,
            hash_height=8,
            min_luma=1.0,
            max_luma=254.0,
            min_variance=1.0,
        )
        debouncer = StableFrameDebouncer(config)
        frame = self._readable_frame()
        moved = np.flip(frame, axis=1)
        debouncer.update(frame)
        result = debouncer.update(moved)
        self.assertFalse(result.is_stable)
        self.assertEqual(result.reason, "motion detected")

    def test_low_contrast_frame_is_rejected(self) -> None:
        debouncer = StableFrameDebouncer(DebounceConfig(min_variance=5.0))
        result = debouncer.update(np.full((32, 32, 3), 120, dtype=np.uint8))
        self.assertFalse(result.is_stable)
        self.assertEqual(result.reason, "frame lacks readable contrast")

    @staticmethod
    def _readable_frame() -> np.ndarray:
        frame = np.zeros((32, 32, 3), dtype=np.uint8) + 40
        frame[:, 16:, :] = 180
        return frame


if __name__ == "__main__":
    unittest.main()
