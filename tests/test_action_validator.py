import unittest

from torn_accessibility_hud.models import RecommendedAction
from torn_accessibility_hud.parsing.action_validator import validate_action_inputs
from torn_accessibility_hud.parsing.amounts import parse_amount_to_call_from_action_text
from torn_accessibility_hud.parsing.legal_actions import normalize_action_text


class ActionValidatorTests(unittest.TestCase):
    def test_check_available_drops_call_without_amount(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("check", "fold", "raise"),
            raw_entries=("check_button_region='Check'",),
            actions_ambiguous=False,
            call_slot_raw="Check",
            action_regions_scanned=True,
        )
        self.assertIn(RecommendedAction.CHECK, result.legal_actions)
        self.assertNotIn(RecommendedAction.CALL, result.legal_actions)
        self.assertEqual(result.to_call, 0.0)
        self.assertIsNone(result.block_reason)

    def test_call_requires_parsed_amount(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("call", "fold", "raise"),
            raw_entries=("call_button_region='Call'",),
            actions_ambiguous=False,
            call_slot_raw="Call",
            action_regions_scanned=True,
        )
        self.assertEqual(result.block_reason, "amount_to_call_unreadable")

    def test_call_with_amount_is_valid(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("call", "fold", "raise"),
            raw_entries=("call_button_region='Call 150'",),
            actions_ambiguous=False,
            call_slot_raw="Call 150",
            action_regions_scanned=True,
        )
        self.assertIn(RecommendedAction.CALL, result.legal_actions)
        self.assertEqual(result.to_call, 150.0)
        self.assertIsNone(result.block_reason)

    def test_prefers_check_over_call_when_amount_zero(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("check", "call", "fold"),
            raw_entries=("call_button_region='Check'",),
            actions_ambiguous=False,
            call_slot_raw="Check",
            action_regions_scanned=True,
        )
        self.assertIn(RecommendedAction.CHECK, result.legal_actions)
        self.assertNotIn(RecommendedAction.CALL, result.legal_actions)

    def test_raise_when_facing_bet(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("call", "fold", "raise"),
            raw_entries=("call_button_region='Call 150'",),
            actions_ambiguous=False,
            call_slot_raw="Call 150",
            action_regions_scanned=True,
        )
        self.assertIn(RecommendedAction.RAISE, result.legal_actions)
        self.assertNotIn(RecommendedAction.BET, result.legal_actions)

    def test_bet_when_no_amount_to_call(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("check", "fold", "raise"),
            raw_entries=("raise_button_region='Bet'",),
            actions_ambiguous=False,
            call_slot_raw="Check",
            raise_slot_raw="Bet",
            action_regions_scanned=True,
        )
        self.assertIn(RecommendedAction.BET, result.legal_actions)
        self.assertNotIn(RecommendedAction.RAISE, result.legal_actions)

    def test_ambiguous_actions_block(self) -> None:
        result = validate_action_inputs(
            normalized_labels=("check",),
            raw_entries=(),
            actions_ambiguous=True,
            call_slot_raw=None,
            action_regions_scanned=True,
        )
        self.assertEqual(result.block_reason, "actions_ambiguous")
        self.assertEqual(result.legal_actions, ())


class LegalActionNormalizationTests(unittest.TestCase):
    def test_ambiguous_text_is_not_defaulted_to_call(self) -> None:
        result = normalize_action_text("chll")
        if result is not None:
            self.assertTrue(result.ambiguous)

    def test_parse_amount_from_call_button(self) -> None:
        amount, status = parse_amount_to_call_from_action_text("Call $150")
        self.assertEqual(status, "ok")
        self.assertEqual(amount, 150.0)


if __name__ == "__main__":
    unittest.main()
