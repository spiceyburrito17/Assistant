import unittest

from torn_accessibility_hud.models import RecommendedAction
from torn_accessibility_hud.parsing.action_validator import validate_action_inputs
from torn_accessibility_hud.parsing.amounts import (
    button_texts_overlap,
    isolate_call_slot_text,
    parse_amount_to_call_from_action_text,
)
from torn_accessibility_hud.parsing.legal_actions import extract_actions_for_button_region


class CallSlotIsolationTests(unittest.TestCase):
    def test_isolate_call_tail_from_combined_bar(self) -> None:
        isolated = isolate_call_slot_text("RAISE TO $20 CALL $20")
        self.assertEqual(isolated, "CALL $20")

    def test_combined_bar_call_amount(self) -> None:
        amount, status = parse_amount_to_call_from_action_text("RAISE TO $20 CALL $10")
        self.assertEqual(status, "ok")
        self.assertEqual(amount, 10.0)

    def test_call_any_sets_zero(self) -> None:
        amount, status = parse_amount_to_call_from_action_text("CALL ANY")
        self.assertEqual(status, "zero")
        self.assertEqual(amount, 0.0)

    def test_check_button_sets_zero(self) -> None:
        amount, status = parse_amount_to_call_from_action_text("CHECK")
        self.assertEqual(status, "zero")
        self.assertEqual(amount, 0.0)

    def test_raise_to_not_used_for_amount(self) -> None:
        amount, status = parse_amount_to_call_from_action_text("RAISE TO $30")
        self.assertEqual(status, "no_call_marker")
        self.assertIsNone(amount)


class PerButtonActionTests(unittest.TestCase):
    def test_call_region_ignores_raise_prefix(self) -> None:
        actions = extract_actions_for_button_region("call_button_region", "RAISE TO $30 CALL $10")
        self.assertEqual({action.label for action in actions}, {"call"})

    def test_raise_region_with_raise_to_is_raise(self) -> None:
        actions = extract_actions_for_button_region("raise_button_region", "RAISE TO $30")
        self.assertEqual([action.label for action in actions], ["raise"])

    def test_combined_validator_unblocks_call_amount(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("fold", "call", "raise"),
            raw_entries=(
                "action_slot_left='RAISE TO $30'",
                "action_slot_centre='RAISE TO $20 CALL $10'",
                "action_slot_right='FOLD'",
            ),
            actions_ambiguous=False,
            call_slot_raw="RAISE TO $20 CALL $10",
            raise_slot_raw="RAISE TO $30",
            action_regions_scanned=True,
        )
        self.assertEqual(result.to_call, 10.0)
        self.assertIsNone(result.block_reason)
        self.assertIn(RecommendedAction.RAISE, result.legal_actions)
        self.assertNotIn(RecommendedAction.BET, result.legal_actions)


class ButtonOverlapTests(unittest.TestCase):
    def test_detects_identical_adjacent_reads(self) -> None:
        self.assertTrue(
            button_texts_overlap("RAISE TO $20 CALL $20", "RAISE TO $20 CALL $20")
        )


if __name__ == "__main__":
    unittest.main()
