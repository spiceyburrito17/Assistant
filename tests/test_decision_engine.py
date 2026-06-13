import unittest

from torn_accessibility_hud.models import (
    DecisionConfidence,
    EquityResult,
    GameSnapshot,
    RecommendationLevel,
    RecommendedAction,
    Street,
)
from torn_accessibility_hud.poker.decision import DecisionEngine
from torn_accessibility_hud.ui.recommendation import RecommendationEngine


class DecisionEngineTests(unittest.TestCase):
    def test_required_equity_and_edge(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            board_cards=("2s", "7h", "Jc"),
            pot_size=200.0,
            to_call=50.0,
            street=Street.FLOP,
            active_opponents=("Fox",),
        )
        result = EquityResult(hero_equity=0.35, tie_rate=0.0, simulations=1000, generation=1, elapsed_ms=10)
        advice = DecisionEngine().build(snapshot, result)
        self.assertAlmostEqual(advice.required_equity or 0.0, 50.0 / 250.0)
        self.assertAlmostEqual(advice.edge or 0.0, 0.35 - (50.0 / 250.0))

    def test_fold_call_raise_thresholds(self) -> None:
        base = GameSnapshot(
            hero_cards=("8c", "2d"),
            board_cards=("Ah", "Kd", "Qs"),
            pot_size=300.0,
            to_call=100.0,
            street=Street.FLOP,
            active_opponents=("Fox",),
        )
        required = 100.0 / 400.0
        engine = DecisionEngine()

        fold = engine.build(
            base,
            EquityResult(hero_equity=required - 0.05, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        call = engine.build(
            base,
            EquityResult(hero_equity=required + 0.01, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        raise_advice = engine.build(
            base,
            EquityResult(hero_equity=0.72, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        self.assertEqual(fold.action, RecommendedAction.FOLD)
        self.assertEqual(call.action, RecommendedAction.CALL)
        self.assertEqual(raise_advice.action, RecommendedAction.RAISE)
        self.assertIsNotNone(raise_advice.raise_sizing)

    def test_check_when_no_call_amount(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            board_cards=("2s", "4h", "9c"),
            pot_size=150.0,
            to_call=0.0,
            street=Street.FLOP,
            active_opponents=("Fox",),
        )
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.40, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        self.assertEqual(advice.required_equity, 0.0)
        self.assertEqual(advice.action, RecommendedAction.CHECK)

    def test_low_confidence_downgrades_raise_to_call(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            board_cards=(),
            pot_size=0.0,
            to_call=25.0,
            street=Street.FLOP,
            active_opponents=("Fox",),
        )
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.70, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        self.assertEqual(advice.confidence, DecisionConfidence.LOW)
        self.assertEqual(advice.action, RecommendedAction.CALL)
        self.assertIn("board cards missing for street", advice.confidence_notes)

    def test_raise_sizing_when_facing_a_bet(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("Ah", "Kh"),
            board_cards=("2h", "7d", "Jc"),
            pot_size=200.0,
            to_call=50.0,
            street=Street.FLOP,
            active_opponents=("Fox",),
        )
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.75, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
        )
        assert advice.raise_sizing is not None
        self.assertAlmostEqual(advice.raise_sizing.min_raise, 100.0)
        self.assertAlmostEqual(advice.raise_sizing.half_pot, 125.0)
        self.assertAlmostEqual(advice.raise_sizing.two_thirds_pot, 500.0 / 3.0)
        self.assertAlmostEqual(advice.raise_sizing.pot, 250.0)


class RecommendationFacadeTests(unittest.TestCase):
    def test_positive_edge_marks_call_or_raise(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            pot_size=1000,
            to_call=100,
            active_opponents=("Fox",),
            generation=3,
        )
        result = EquityResult(hero_equity=0.35, tie_rate=0.02, simulations=1000, generation=3, elapsed_ms=20)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertIn(recommendation.action, {RecommendedAction.CALL, RecommendedAction.RAISE})
        self.assertIn(recommendation.level, {RecommendationLevel.SAFE, RecommendationLevel.CAUTION})

    def test_recommendation_reuses_recent_equity_when_generation_is_one_off(self) -> None:
        snapshot = GameSnapshot(
            hero_cards=("As", "Kd"),
            pot_size=1000,
            to_call=100,
            active_opponents=("Fox",),
            generation=4,
        )
        result = EquityResult(hero_equity=0.35, tie_rate=0.0, simulations=100, generation=3, elapsed_ms=10)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertIsNotNone(recommendation.edge)

    def test_recommendation_waits_for_stale_generation(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=("Fox",), generation=10)
        result = EquityResult(hero_equity=0.9, tie_rate=0.0, simulations=100, generation=3, elapsed_ms=10)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertEqual(recommendation.level, RecommendationLevel.WAIT)


if __name__ == "__main__":
    unittest.main()
