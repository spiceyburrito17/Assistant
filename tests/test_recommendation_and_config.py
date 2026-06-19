import json
import tempfile
import unittest
from pathlib import Path

from torn_accessibility_hud.config import AppConfig, RegionsConfig


class RecommendationAndConfigTests(unittest.TestCase):
    def test_config_loads_nested_region_and_gpu_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "capture": {"region": {"left": 10, "top": 20, "width": 300, "height": 200}},
                        "ocr": {
                            "languages": ["en"],
                            "gpu": True,
                            "hero_cards_region": {"left": 1, "top": 2, "width": 3, "height": 4},
                            "board_cards_region": {"left": 5, "top": 6, "width": 7, "height": 8},
                            "debug_card_regions": True,
                            "debug_card_regions_dir": "debug_captures/test_cards",
                            "debug_card_regions_interval_sec": 1.5,
                            "hero_cards_interval_sec": 0.0,
                            "card_ocr_scale": 4.0,
                            "card_ocr_allowlist": "0123456789AaKkQqJjTt",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = AppConfig.load(path)
        self.assertEqual(config.capture.region.left, 10)
        self.assertTrue(config.ocr.gpu)
        self.assertEqual(config.ocr.languages, ("en",))
        self.assertTrue(config.ocr.debug_card_regions)
        self.assertIsNotNone(config.ocr.hero_cards_region)
        self.assertIsNotNone(config.ocr.board_cards_region)
        assert config.ocr.hero_cards_region is not None
        assert config.ocr.board_cards_region is not None
        self.assertEqual(config.ocr.hero_cards_region.left, 1)
        self.assertEqual(config.ocr.board_cards_region.width, 7)
        self.assertEqual(config.ocr.debug_card_regions_dir, "debug_captures/test_cards")
        self.assertEqual(config.ocr.debug_card_regions_interval_sec, 1.5)
        self.assertEqual(config.ocr.hero_cards_interval_sec, 0.0)
        self.assertEqual(config.ocr.card_ocr_scale, 4.0)
        self.assertEqual(config.ocr.card_ocr_allowlist, "0123456789AaKkQqJjTt")

    def test_regions_config_loads_named_regions_and_extras(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "regions_calibrated.json"
            path.write_text(
                json.dumps(
                    {
                        "log_region": {"left": 10, "top": 20, "width": 300, "height": 100},
                        "hero_cards_region": {"left": 30, "top": 40, "width": 80, "height": 40},
                        "region_0": {"left": 50, "top": 60, "width": 20, "height": 10},
                    }
                ),
                encoding="utf-8",
            )
            regions = RegionsConfig.load(path)
        self.assertIsNotNone(regions.log_region)
        assert regions.log_region is not None
        self.assertEqual(regions.log_region.left, 10)
        self.assertIsNotNone(regions.hero_cards_region)
        self.assertIn("region_0", regions.as_dict())

    def test_regions_config_rejects_non_positive_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "regions_calibrated.json"
            path.write_text(
                json.dumps({"log_region": {"left": 10, "top": 20, "width": 0, "height": 100}}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                RegionsConfig.load(path)


if __name__ == "__main__":
    unittest.main()
