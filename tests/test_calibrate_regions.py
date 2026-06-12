import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


def _load_calibration_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "tools" / "calibrate_regions.py"
    spec = importlib.util.spec_from_file_location("calibrate_regions", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load calibrate_regions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CalibrateRegionsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
