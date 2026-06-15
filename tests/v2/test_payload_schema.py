"""Tests for userscript payload schema validation."""

from __future__ import annotations

import json
import unittest

from torn_hud_v2.models.messages import TableDeltaMessage


class PayloadSchemaTests(unittest.TestCase):
    def test_parse_table_delta(self) -> None:
        message = TableDeltaMessage.from_json(
            json.dumps(
                {
                    "schema_version": 1,
                    "message_type": "table_delta",
                    "seq": 7,
                    "ts_ms": 1718280000000,
                    "pot_raw": "POT: $18K",
                    "pot_parsed": 18000,
                    "hero_cards": ["Ah", "Kd"],
                    "board_cards": ["2s", "7h", "Jc"],
                    "hero_turn": True,
                    "slot_left_raw": "RAISE TO $240",
                    "slot_centre_raw": "CALL $120",
                    "slot_right_raw": "FOLD",
                    "amount_to_call_parsed": 120,
                    "legal_actions": ["fold", "call", "raise"],
                    "post_hand_ui": False,
                }
            )
        )
        self.assertTrue(message.is_table_delta)
        self.assertEqual(message.pot_parsed, 18000.0)
        self.assertEqual(message.hero_cards, ("Ah", "Kd"))
        self.assertEqual(message.legal_actions, ("fold", "call", "raise"))

    def test_rejects_unknown_message_type(self) -> None:
        with self.assertRaises(ValueError):
            TableDeltaMessage.from_json(json.dumps({"message_type": "click_action"}))

    def test_ping_is_not_table_delta(self) -> None:
        message = TableDeltaMessage.from_json(
            json.dumps({"schema_version": 1, "message_type": "ping", "seq": 1, "ts_ms": 1})
        )
        self.assertFalse(message.is_table_delta)


if __name__ == "__main__":
    unittest.main()
