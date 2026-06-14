"""Tests for fixed action-bar slot parsing."""

from __future__ import annotations

import unittest

from torn_accessibility_hud.models import ActionSlotOCRResult, TableOCRResult
from torn_accessibility_hud.parsing.action_slots import classify_slot_text, parse_action_bar


class ActionSlotParsingTests(unittest.TestCase):
    def test_classify_facing_bet_layout(self) -> None:
        self.assertEqual(classify_slot_text("action_slot_left", "RAISE TO $40").label, "raise")
        self.assertEqual(classify_slot_text("action_slot_centre", "CALL $20").label, "call")
        self.assertEqual(classify_slot_text("action_slot_right", "FOLD").label, "fold")

    def test_classify_checked_to_layout(self) -> None:
        self.assertEqual(classify_slot_text("action_slot_left", "RAISE TO $20").label, "raise")
        self.assertEqual(classify_slot_text("action_slot_centre", "CHECK").label, "check")
        self.assertEqual(classify_slot_text("action_slot_right", "FOLD").label, "fold")

    def test_classify_pre_action_toggle(self) -> None:
        result = classify_slot_text("action_slot_left", "CALL ANY / CHECK")
        self.assertEqual(result.label, "check")
        self.assertTrue(result.pre_action_toggle)

    def test_call_any_sets_zero_to_call(self) -> None:
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="CALL ANY"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="CHECK"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="FOLD"),
            ),
            action_regions_scanned=True,
        )
        parsed = parse_action_bar(table_ocr)
        self.assertEqual(set(parsed.legal_actions_normalized), {"check", "fold"})
        self.assertEqual(parsed.amount_to_call_parsed, 0.0)

    def test_post_hand_skips_action_parsing(self) -> None:
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="SHOW CARDS"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="SIT OUT LEAVE"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="LEAVE"),
            ),
            action_regions_scanned=True,
        )
        parsed = parse_action_bar(table_ocr)
        self.assertTrue(parsed.post_hand_ui)
        self.assertEqual(parsed.block_reason, "post_hand")
        self.assertEqual(parsed.legal_actions, ())

    def test_parse_action_bar_builds_normalized_actions(self) -> None:
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(
                    slot_name="action_slot_left",
                    ocr_scan_raw="RAISE TO $40",
                    region_coords="-1305,894,200,45",
                ),
                ActionSlotOCRResult(
                    slot_name="action_slot_centre",
                    ocr_scan_raw="CALL $20",
                    region_coords="-1095,894,200,45",
                ),
                ActionSlotOCRResult(
                    slot_name="action_slot_right",
                    ocr_scan_raw="FOLD",
                    region_coords="-838,893,212,45",
                ),
            ),
            action_regions_scanned=True,
        )
        parsed = parse_action_bar(table_ocr)
        self.assertEqual(set(parsed.legal_actions_normalized), {"raise", "call", "fold"})
        self.assertEqual(parsed.amount_to_call_parsed, 20.0)
        self.assertEqual(parsed.slot_left_raw, "RAISE TO $40")

    def test_unclassified_slot_does_not_block_when_actions_found(self) -> None:
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="RAISE TO $40"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="CALL $20"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="???"),
            ),
            action_regions_scanned=True,
        )
        parsed = parse_action_bar(table_ocr)
        self.assertFalse(parsed.actions_ambiguous)
        self.assertEqual(set(parsed.legal_actions_normalized), {"raise", "call"})


if __name__ == "__main__":
    unittest.main()
