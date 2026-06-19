"""Tests for action slot classification."""

from __future__ import annotations

import unittest

from torn_hud_v2.normalization.action_slots import (
    amount_to_call_from_slots,
    classify_slot_text,
    legal_actions_from_slots,
)


class ActionSlotTests(unittest.TestCase):
    def test_call_any_normalizes_to_check(self) -> None:
        self.assertEqual(classify_slot_text("CALL ANY"), "check")
        self.assertEqual(legal_actions_from_slots(("FOLD", "CALL ANY", "RAISE TO $50")), ("fold", "check", "raise"))

    def test_post_hand_labels_not_classified(self) -> None:
        self.assertIsNone(classify_slot_text("SHOW CARDS"))
        self.assertIsNone(classify_slot_text("SIT OUT"))
        self.assertEqual(legal_actions_from_slots(("SHOW CARDS", "SIT OUT", "LEAVE")), ())

    def test_amount_to_call_from_call_any_is_zero(self) -> None:
        raw, parsed = amount_to_call_from_slots(("", "CALL ANY", "FOLD"))
        self.assertEqual(raw, "CALL ANY")
        self.assertEqual(parsed, 0.0)

    def test_amount_to_call_from_call_with_money(self) -> None:
        raw, parsed = amount_to_call_from_slots(("RAISE TO $240", "CALL $120", "FOLD"))
        self.assertEqual(raw, "CALL $120")
        self.assertEqual(parsed, 120.0)


if __name__ == "__main__":
    unittest.main()
