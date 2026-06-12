import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


def _load_calibration_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "tools" / "calibrate_regions.py"
    spec = importlib.util.spec_from_file_location("calibrate_regions", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load calibrate_regions.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_regions"] = module
    spec.loader.exec_module(module)
    return module


class CalibrateRegionsTests(unittest.TestCase):
    def test_choose_monitor_defaults_to_leftmost_physical_monitor(self) -> None:
        module = _load_calibration_module()
        monitors = [
            {"left": -1920, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080},
        ]
        self.assertEqual(module.choose_monitor(monitors, None), monitors[2])

    def test_choose_monitor_allows_explicit_index(self) -> None:
        module = _load_calibration_module()
        monitors = [
            {"left": -1920, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": -1920, "top": 0, "width": 1920, "height": 1080},
        ]
        self.assertEqual(module.choose_monitor(monitors, 1), monitors[1])

    def test_label_regions_adds_monitor_offset_and_extra_names(self) -> None:
        module = _load_calibration_module()
        regions = module.label_regions(
            (
                (1, 2, 30, 40),
                (5, 6, 70, 80),
                (9, 10, 90, 100),
                (11, 12, 110, 120),
                (13, 14, 130, 140),
            ),
            monitor_left=1000,
            monitor_top=200,
        )
        self.assertEqual(regions["log_region"], {"left": 1001, "top": 202, "width": 30, "height": 40})
        self.assertEqual(regions["hero_cards_region"]["left"], 1005)
        self.assertEqual(regions["board_cards_region"]["top"], 210)
        self.assertEqual(regions["stack_region"]["width"], 110)
        self.assertEqual(regions["region_0"], {"left": 1013, "top": 214, "width": 130, "height": 140})

    def test_label_regions_skips_empty_rectangles(self) -> None:
        module = _load_calibration_module()
        regions = module.label_regions(((1, 2, 0, 40), (5, 6, 70, 80)), monitor_left=0, monitor_top=0)
        self.assertNotIn("log_region", regions)
        self.assertEqual(regions["hero_cards_region"], {"left": 5, "top": 6, "width": 70, "height": 80})

    def test_roi_selector_q_key_closes_window(self) -> None:
        module = _load_calibration_module()
        fake_cv2 = _FakeCv2(key=ord("q"))
        selector = module.ROISelector(screenshot_bgr=_FakeImage(), cv2=fake_cv2, window_name="test")
        self.assertEqual(selector.run(), ())
        self.assertTrue(fake_cv2.destroyed)


class _FakeImage:
    def copy(self) -> "_FakeImage":
        return self


class _FakeCv2:
    WINDOW_NORMAL = 0
    FONT_HERSHEY_SIMPLEX = 0
    EVENT_LBUTTONDOWN = 1
    EVENT_MOUSEMOVE = 2
    EVENT_LBUTTONUP = 3

    def __init__(self, key: int) -> None:
        self.key = key
        self.destroyed = False

    def namedWindow(self, _window_name: str, _flags: int) -> None:
        return None

    def setMouseCallback(self, _window_name: str, _callback: object) -> None:
        return None

    def imshow(self, _window_name: str, _image: object) -> None:
        return None

    def waitKey(self, _delay: int) -> int:
        return self.key

    def destroyWindow(self, _window_name: str) -> None:
        self.destroyed = True

    def putText(self, *_args: object) -> None:
        return None

    def rectangle(self, *_args: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
