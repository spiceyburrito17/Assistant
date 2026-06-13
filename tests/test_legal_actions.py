import unittest

from torn_accessibility_hud.models import ButtonOCRResult, GameSnapshot, PotOCRResult, RecommendedAction, TableOCRResult
from torn_accessibility_hud.parsing.amounts import parse_pot_amount_from_text, parse_to_call_from_button_text
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
        self.assertEqual(parse_pot_amount_from_text("$1,250"), 1250.0)

    def test_call_button_amount_parses_to_call(self) -> None:
        self.assertEqual(parse_to_call_from_button_text("Call 150"), 150.0)


class ButtonRegionActionTests(unittest.TestCase):
    def test_button_regions_use_expected_labels(self) -> None:
        manager = TrustedTableStateManager()
        table_ocr = TableOCRResult(
            buttons=(
                ButtonOCRResult(
                    region_name="check_button_region",
                    raw_text="Check",
                    normalized_label="check",
                    confidence=0.95,
                    ambiguous=False,
                    expected_label="check",
                    detected_labels=("check",),
                ),
                ButtonOCRResult(
                    region_name="fold_button_region",
                    raw_text="Fold",
                    normalized_label="fold",
                    confidence=0.95,
                    ambiguous=False,
                    expected_label="fold",
                    detected_labels=("fold",),
                ),
            ),
            action_regions_scanned=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(),
            (),
            (),
            table_ocr=table_ocr,
        )
        self.assertIn(RecommendedAction.CHECK, snapshot.legal_actions)
        self.assertIn(RecommendedAction.FOLD, snapshot.legal_actions)
        self.assertNotIn(RecommendedAction.CALL, snapshot.legal_actions)
        self.assertFalse(trusted.actions_ambiguous)

    def test_check_in_call_slot_is_accepted(self) -> None:
        manager = TrustedTableStateManager()
        table_ocr = TableOCRResult(
            pot=PotOCRResult(raw_text="$200", parsed_amount=200.0, ocr_confidence=0.9, allowlist="$"),
            buttons=(
                ButtonOCRResult(
                    region_name="call_button_region",
                    raw_text="Check",
                    normalized_label="check",
                    confidence=0.95,
                    ambiguous=False,
                    expected_label="call",
                    detected_labels=("check",),
                ),
                ButtonOCRResult(
                    region_name="fold_button_region",
                    raw_text="Fold",
                    normalized_label="fold",
                    confidence=0.95,
                    ambiguous=False,
                    expected_label="fold",
                    detected_labels=("fold",),
                ),
            ),
            pot_region_scanned=True,
            action_regions_scanned=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            table_ocr=table_ocr,
        )
        self.assertIn(RecommendedAction.CHECK, snapshot.legal_actions)
        self.assertNotIn(RecommendedAction.CALL, snapshot.legal_actions)
        self.assertFalse(trusted.actions_ambiguous)

    def test_wide_check_region_can_emit_check_and_fold(self) -> None:
        manager = TrustedTableStateManager()
        table_ocr = TableOCRResult(
            pot=PotOCRResult(raw_text="$200", parsed_amount=200.0, ocr_confidence=0.9, allowlist="$"),
            buttons=(
                ButtonOCRResult(
                    region_name="check_button_region",
                    raw_text="Check Fold",
                    normalized_label="check",
                    confidence=0.95,
                    ambiguous=False,
                    expected_label="check",
                    detected_labels=("check", "fold"),
                ),
            ),
            pot_region_scanned=True,
            action_regions_scanned=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            table_ocr=table_ocr,
        )
        self.assertIn(RecommendedAction.CHECK, snapshot.legal_actions)
        self.assertIn(RecommendedAction.FOLD, snapshot.legal_actions)
        self.assertFalse(trusted.actions_ambiguous)


if __name__ == "__main__":
    unittest.main()
