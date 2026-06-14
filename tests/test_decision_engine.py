import unittest

from torn_accessibility_hud.models import (
    EquityResult,
    GameSnapshot,
    RecommendationLevel,
    RecommendedAction,
    SolverStatus,
    Street,
    TableStateConfidence,
)
from torn_accessibility_hud.parsing.legal_actions import parse_legal_actions_from_lines
from torn_accessibility_hud.poker.decision import DecisionEngine
from torn_accessibility_hud.poker.equity_sanity import sanitize_equity_result
from torn_accessibility_hud.state import TrustedTableStateManager
from torn_accessibility_hud.ui.recommendation import RecommendationEngine


def _trusted_snapshot(**overrides: object) -> GameSnapshot:
    base = {
        "hero_cards": ("As", "Kd"),
        "board_cards": ("2s", "7h", "Jc"),
        "pot_size": 200.0,
        "to_call": 50.0,
        "street": Street.FLOP,
        "active_opponents": ("Fox",),
        "legal_actions": (RecommendedAction.FOLD, RecommendedAction.CALL, RecommendedAction.RAISE),
        "state_confidence": TableStateConfidence.HIGH,
        "generation": 1,
    }
    base.update(overrides)
    return GameSnapshot(**base)


class DecisionEngineTests(unittest.TestCase):
    def test_required_equity_and_edge(self) -> None:
        snapshot = _trusted_snapshot()
        result = EquityResult(hero_equity=0.35, tie_rate=0.0, simulations=1000, generation=1, elapsed_ms=10)
        advice = DecisionEngine().build(snapshot, result, solver_status=SolverStatus.OK)
        self.assertAlmostEqual(advice.required_equity or 0.0, 50.0 / 250.0)
        self.assertAlmostEqual(advice.edge or 0.0, 0.35 - (50.0 / 250.0))

    def test_fold_call_raise_thresholds(self) -> None:
        base = _trusted_snapshot(hero_cards=("8c", "2d"), board_cards=("Ah", "Kd", "Qs"), pot_size=300.0, to_call=100.0)
        required = 100.0 / 400.0
        engine = DecisionEngine()

        fold = engine.build(
            base,
            EquityResult(hero_equity=required - 0.05, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        call = engine.build(
            base,
            EquityResult(hero_equity=required + 0.01, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        raise_advice = engine.build(
            base,
            EquityResult(hero_equity=0.72, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        self.assertEqual(fold.action, RecommendedAction.FOLD)
        self.assertEqual(call.action, RecommendedAction.CALL)
        self.assertEqual(raise_advice.action, RecommendedAction.RAISE)
        self.assertIsNotNone(raise_advice.raise_sizing)

    def test_check_when_no_call_amount_and_check_is_legal(self) -> None:
        snapshot = _trusted_snapshot(
            board_cards=("2s", "4h", "9c"),
            pot_size=150.0,
            to_call=0.0,
            legal_actions=(RecommendedAction.FOLD, RecommendedAction.CHECK, RecommendedAction.RAISE),
        )
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.40, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        self.assertEqual(advice.required_equity, 0.0)
        self.assertEqual(advice.action, RecommendedAction.CHECK)

    def test_check_blocked_when_only_raise_and_fold_visible(self) -> None:
        snapshot = _trusted_snapshot(
            to_call=0.0,
            legal_actions=(RecommendedAction.FOLD, RecommendedAction.RAISE),
        )
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.40, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        self.assertEqual(advice.action, RecommendedAction.WAIT)
        self.assertIn("check not in legal_actions", advice.decision_blocked_reason or "")

    def test_missing_pot_blocks_action(self) -> None:
        snapshot = _trusted_snapshot(pot_size=0.0, state_confidence=TableStateConfidence.LOW)
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.70, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        self.assertEqual(advice.action, RecommendedAction.WAIT)
        self.assertEqual(advice.decision_blocked_reason, "pot_unreadable")

    def test_solver_timeout_blocks_action(self) -> None:
        snapshot = _trusted_snapshot()
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(
                hero_equity=0.70,
                tie_rate=0.0,
                simulations=100,
                generation=1,
                elapsed_ms=10,
                warning="simulation budget hit timeout",
            ),
            solver_status=SolverStatus.TIMEOUT,
        )
        self.assertEqual(advice.action, RecommendedAction.WAIT)
        self.assertEqual(advice.decision_blocked_reason, "simulation budget hit timeout")

    def test_raise_sizing_when_facing_a_bet(self) -> None:
        snapshot = _trusted_snapshot(hero_cards=("Ah", "Kh"))
        advice = DecisionEngine().build(
            snapshot,
            EquityResult(hero_equity=0.75, tie_rate=0.0, simulations=500, generation=1, elapsed_ms=10),
            solver_status=SolverStatus.OK,
        )
        assert advice.raise_sizing is not None
        self.assertAlmostEqual(advice.raise_sizing.min_raise, 100.0)


class RecommendationFacadeTests(unittest.TestCase):
    def test_positive_edge_marks_call_or_raise(self) -> None:
        snapshot = _trusted_snapshot(pot_size=1000, to_call=100, generation=3)
        result = EquityResult(hero_equity=0.35, tie_rate=0.02, simulations=1000, generation=3, elapsed_ms=20)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertIn(recommendation.action, {RecommendedAction.CALL, RecommendedAction.RAISE})
        self.assertIn(recommendation.level, {RecommendationLevel.SAFE, RecommendationLevel.CAUTION})

    def test_recommendation_reuses_recent_equity_when_generation_is_one_off(self) -> None:
        snapshot = _trusted_snapshot(pot_size=1000, to_call=100, generation=4)
        result = EquityResult(hero_equity=0.35, tie_rate=0.0, simulations=100, generation=3, elapsed_ms=10)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertIsNotNone(recommendation.edge)

    def test_recommendation_waits_for_stale_generation(self) -> None:
        snapshot = _trusted_snapshot(pot_size=1000, to_call=100, generation=10)
        result = EquityResult(hero_equity=0.9, tie_rate=0.0, simulations=100, generation=3, elapsed_ms=10)
        recommendation = RecommendationEngine().build(snapshot, result)
        self.assertEqual(recommendation.level, RecommendationLevel.WAIT)


class LegalActionParsingTests(unittest.TestCase):
    def test_parse_raise_and_fold_buttons(self) -> None:
        actions = parse_legal_actions_from_lines(("Raise", "Fold"))
        self.assertEqual(actions, (RecommendedAction.RAISE, RecommendedAction.FOLD))

    def test_parse_call_check_fold(self) -> None:
        actions = parse_legal_actions_from_lines(("Call 50", "Check", "Fold"))
        self.assertEqual(
            actions,
            (RecommendedAction.CALL, RecommendedAction.CHECK, RecommendedAction.FOLD),
        )


class TrustedTableStateTests(unittest.TestCase):
    def test_board_persists_through_short_misses(self) -> None:
        manager = TrustedTableStateManager(board_regress_scans=8)
        from torn_accessibility_hud.models import ActionType, ParsedEvent

        manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h", "Ks")),
            (
                ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),
                ParsedEvent(action=ActionType.BOARD, raw_text="Board: 2s 4h Ks", cards=("2s", "4h", "Ks")),
            ),
            (),
            board_cards_scanned=True,
        )
        for _ in range(5):
            trusted, snapshot = manager.apply(
                GameSnapshot(hero_cards=("As", "Kd")),
                (),
                (),
                board_cards_scanned=True,
            )
        self.assertEqual(snapshot.board_cards, ("2s", "4h", "Ks"))

    def test_pot_persists_until_replaced(self) -> None:
        manager = TrustedTableStateManager()
        from torn_accessibility_hud.models import ActionType, ParsedEvent

        manager.apply(
            GameSnapshot(pot_size=250.0),
            (ParsedEvent(action=ActionType.POT, raw_text="Pot 250", amount=250.0),),
            ("Fold", "Call", "Raise"),
        )
        trusted, snapshot = manager.apply(GameSnapshot(), (), ("Fold", "Call", "Raise"))
        self.assertEqual(trusted.pot_size, 250.0)
        self.assertEqual(snapshot.pot_size, 250.0)


class EquitySanityTests(unittest.TestCase):
    def test_no_opponents_runs_with_anonymous_villain(self) -> None:
        from torn_accessibility_hud.poker.equity import MonteCarloEquityCalculator

        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=(), generation=1)
        result = MonteCarloEquityCalculator(seed=1).calculate(snapshot, {}, simulations=100, timeout_ms=500)
        self.assertIsNotNone(result.hero_equity)
        self.assertGreater(result.simulations, 0)

    def test_zero_sim_warning_is_not_ok_status(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=())
        result = EquityResult(None, 0.0, 0, 1, 0.0, "insufficient state")
        sanitized, status = sanitize_equity_result(result, snapshot)
        self.assertIsNone(sanitized.hero_equity)
        self.assertEqual(status, SolverStatus.INSUFFICIENT_STATE)

    def test_partial_timeout_with_enough_sims_is_ok(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=("villain",))
        result = EquityResult(
            hero_equity=0.55,
            tie_rate=0.0,
            simulations=150,
            generation=1,
            elapsed_ms=900.0,
            warning="simulation budget hit timeout after 150 simulations",
        )
        sanitized, status = sanitize_equity_result(result, snapshot)
        self.assertEqual(status, SolverStatus.OK)
        self.assertAlmostEqual(sanitized.hero_equity or 0.0, 0.55)

    def test_timeout_with_few_sims_stays_blocked(self) -> None:
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), active_opponents=("villain",))
        result = EquityResult(
            hero_equity=0.55,
            tie_rate=0.0,
            simulations=50,
            generation=1,
            elapsed_ms=900.0,
            warning="simulation budget hit timeout after 50 simulations",
        )
        sanitized, status = sanitize_equity_result(result, snapshot)
        self.assertEqual(status, SolverStatus.TIMEOUT)
        self.assertIsNone(sanitized.hero_equity)


if __name__ == "__main__":
    unittest.main()
