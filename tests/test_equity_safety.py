import unittest

from torn_accessibility_hud.models import GameSnapshot, RecommendationLevel
from torn_accessibility_hud.poker.equity import MonteCarloEquityCalculator
from torn_accessibility_hud.ui.recommendation import RecommendationEngine


class EquitySafetyTests(unittest.TestCase):
    def test_partial_flop_returns_awaiting_full_flop_without_treys(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            board_cards=("2s", "4h"),
            active_opponents=("Villain",),
            generation=7,
        )
        result = MonteCarloEquityCalculator(seed=1).calculate(snapshot, {}, simulations=10, timeout_ms=10)
        self.assertIsNone(result.hero_equity)
        self.assertEqual(result.warning, "Awaiting Full Flop")
        self.assertEqual(result.generation, 7)

    def test_invalid_board_count_returns_none_equity(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            board_cards=("2s", "4h", "Ks", "5s", "9c", "Td"),
            active_opponents=("Villain",),
            generation=8,
        )
        result = MonteCarloEquityCalculator(seed=1).calculate(snapshot, {}, simulations=10, timeout_ms=10)
        self.assertIsNone(result.hero_equity)
        self.assertEqual(result.warning, "Invalid board card count")

    def test_recommendation_handles_none_equity_as_dealing(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h"), generation=7)
        result = MonteCarloEquityCalculator(seed=1).calculate(
            snapshot,
            {"Villain": {}},
            simulations=10,
            timeout_ms=10,
        )
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertEqual(recommendation.level, RecommendationLevel.UNKNOWN)
        self.assertEqual(recommendation.title, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
