import json
import tempfile
import unittest
from pathlib import Path

from torn_accessibility_hud.config import AppConfig
from torn_accessibility_hud.models import EquityResult, GameSnapshot, RecommendationLevel
from torn_accessibility_hud.ui.recommendation import RecommendationEngine


class RecommendationAndConfigTests(unittest.TestCase):
    def test_recommendation_marks_positive_edge_green(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), pot_size=1000, to_call=100, active_opponents=("Fox",), generation=3)
        result = EquityResult(hero_equity=0.35, tie_rate=0.02, simulations=1000, generation=3, elapsed_ms=20)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertEqual(recommendation.level, RecommendationLevel.SAFE)

    def test_recommendation_waits_for_matching_generation(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=("Fox",), generation=4)
        result = EquityResult(hero_equity=0.9, tie_rate=0.0, simulations=100, generation=3, elapsed_ms=10)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertEqual(recommendation.level, RecommendationLevel.WAIT)

    def test_config_loads_nested_region_and_gpu_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "capture": {"region": {"left": 10, "top": 20, "width": 300, "height": 200}},
                        "ocr": {"languages": ["en"], "gpu": True},
                    }
                ),
                encoding="utf-8",
            )
            config = AppConfig.load(path)
        self.assertEqual(config.capture.region.left, 10)
        self.assertTrue(config.ocr.gpu)
        self.assertEqual(config.ocr.languages, ("en",))


if __name__ == "__main__":
    unittest.main()
