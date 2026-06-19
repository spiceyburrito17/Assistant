import unittest

from torn_accessibility_hud.models import GameSnapshot, PotOCRResult, RecommendedAction, TableOCRResult
from torn_accessibility_hud.parsing.amounts import parse_to_call_from_button_text
from torn_accessibility_hud.parsing.pot_parser import parse_pot_text
from torn_accessibility_hud.parsing.legal_actions import (
    extract_actions_from_region_text,
    normalize_action_text,
    parse_legal_actions_from_lines,
)
from torn_accessibility_hud.state import TrustedTableStateManager


class LegalActionNormalizationTests(unittest.TestCase):
    def test_check_is_not_mapped_to_call(self) -> None:
        result = normalize_action_text("Check")
        assert result is not None
        self.assertEqual(result.label, "check")
        self.assertFalse(result.ambiguous)

    def test_call_with_amount_normalizes_to_call(self) -> None:
        result = normalize_action_text("Call 150")
        assert result is not None
        self.assertEqual(result.label, "call")

    def test_check_beats_call_for_cheek_ocr(self) -> None:
        result = normalize_action_text("Cheek")
        assert result is not None
        self.assertEqual(result.label, "check")

    def test_wide_region_extracts_check_and_fold(self) -> None:
        actions = extract_actions_from_region_text("Check Fold")
        self.assertEqual({action.label for action in actions}, {"check", "fold"})

    def test_unrecognized_line_is_not_emitted(self) -> None:
        actions = parse_legal_actions_from_lines(("xyz",))
        self.assertEqual(actions, ())

    def test_raise_and_fold_from_lines(self) -> None:
        actions = parse_legal_actions_from_lines(("Raise", "Fold"))
        self.assertEqual({action.value for action in actions}, {"raise", "fold"})


class PotParsingTests(unittest.TestCase):
    def test_pot_amount_parses_currency(self) -> None:
        amount, _status = parse_pot_text("POT: $1,250")
        self.assertEqual(amount, 1250.0)

    def test_call_button_amount_parses_to_call(self) -> None:
        self.assertEqual(parse_to_call_from_button_text("Call 150"), 150.0)


class ActionSlotIntegrationTests(unittest.TestCase):
    def test_action_slots_build_legal_actions(self) -> None:
        from torn_accessibility_hud.models import ActionSlotOCRResult

        manager = TrustedTableStateManager()
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="RAISE TO $30"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="CHECK"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="FOLD"),
            ),
            action_regions_scanned=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), pot_size=200.0),
            (),
            (),
            hero_cards_scanned=True,
            hero_cards_stable=True,
            table_ocr=table_ocr,
        )
        self.assertIn(RecommendedAction.RAISE, snapshot.legal_actions)
        self.assertIn(RecommendedAction.CHECK, snapshot.legal_actions)
        self.assertIn(RecommendedAction.FOLD, snapshot.legal_actions)
        self.assertFalse(trusted.actions_ambiguous)

    def test_facing_bet_layout_parses_call_amount(self) -> None:
        from torn_accessibility_hud.models import ActionSlotOCRResult

        manager = TrustedTableStateManager()
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="RAISE TO $40"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="CALL $20"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="FOLD"),
            ),
            action_regions_scanned=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), pot_size=500.0),
            (),
            (),
            hero_cards_scanned=True,
            hero_cards_stable=True,
            table_ocr=table_ocr,
        )
        self.assertIn(RecommendedAction.CALL, snapshot.legal_actions)
        assert trusted.parse_diagnostics is not None
        self.assertEqual(trusted.parse_diagnostics.amount_to_call_parsed, 20.0)


if __name__ == "__main__":
    unittest.main()
