"""Tests for OCR-tolerant slot dollar amount normalisation."""

from __future__ import annotations

import unittest

from torn_accessibility_hud.models import ActionSlotOCRResult, TableOCRResult
from torn_accessibility_hud.parsing.action_slots import classify_slot_text, parse_action_bar
from torn_accessibility_hud.parsing.slot_amounts import (
    normalize_slot_action_text_for_amounts,
    normalize_slot_money_token,
    parse_amount_to_call_from_slot_text,
    parse_raise_to_amount_from_action_text,
)


class SlotMoneyTokenTests(unittest.TestCase):
    def test_leading_s_becomes_dollar(self) -> None:
        self.assertEqual(normalize_slot_money_token("Szo"), "$20")
        self.assertEqual(normalize_slot_money_token("szoo"), "$200")

    def test_ocr_digit_map(self) -> None:
        self.assertEqual(normalize_slot_money_token("SIZO"), "$120")

    def test_call_any_is_not_rewritten(self) -> None:
        self.assertEqual(normalize_slot_action_text_for_amounts("CALL ANY"), "CALL ANY")

    def test_call_amount_normalisation(self) -> None:
        self.assertEqual(normalize_slot_action_text_for_amounts("CALL Szo"), "CALL $20")
        self.assertEqual(normalize_slot_action_text_for_amounts("CaLL Szo"), "CaLL $20")

    def test_raise_to_amount_normalisation(self) -> None:
        self.assertEqual(normalize_slot_action_text_for_amounts("RAISE TO Szoo"), "RAISE TO $200")

    def test_parse_call_amounts(self) -> None:
        parsed, status = parse_amount_to_call_from_slot_text("CALL Szo")
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, 20.0)

        parsed, status = parse_amount_to_call_from_slot_text("CALL SIZO")
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, 120.0)

    def test_parse_raise_to_amount(self) -> None:
        self.assertEqual(parse_raise_to_amount_from_action_text("RAISE TO Szoo"), 200.0)
        self.assertEqual(parse_raise_to_amount_from_action_text("RAISE TO $18K"), 18000.0)


class SlotAmountSuffixTests(unittest.TestCase):
    def test_call_amount_k_suffix(self) -> None:
        parsed, status = parse_amount_to_call_from_slot_text("CALL $18K")
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, 18000.0)

    def test_call_amount_fractional_k_suffix(self) -> None:
        parsed, status = parse_amount_to_call_from_slot_text("CALL $1.2K")
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, 1200.0)

    def test_call_amount_m_suffix(self) -> None:
        parsed, status = parse_amount_to_call_from_slot_text("CALL $1M")
        self.assertEqual(status, "ok")
        self.assertEqual(parsed, 1_000_000.0)


class SlotOCRIntegrationTests(unittest.TestCase):
    def test_parse_action_bar_with_ocr_corrupted_call(self) -> None:
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(slot_name="action_slot_left", ocr_scan_raw="RAISE TO Szoo"),
                ActionSlotOCRResult(slot_name="action_slot_centre", ocr_scan_raw="CALL Szo"),
                ActionSlotOCRResult(slot_name="action_slot_right", ocr_scan_raw="FOLD"),
            ),
            action_regions_scanned=True,
        )
        parsed = parse_action_bar(table_ocr)
        self.assertEqual(set(parsed.legal_actions_normalized), {"raise", "call", "fold"})
        self.assertEqual(parsed.amount_to_call_parsed, 20.0)
        self.assertIsNone(parsed.block_reason)

    def test_classify_call_with_ocr_amount(self) -> None:
        result = classify_slot_text("action_slot_centre", "CALL Szo")
        self.assertEqual(result.label, "call")


if __name__ == "__main__":
    unittest.main()
