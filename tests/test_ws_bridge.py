"""Tests for the Tampermonkey WebSocket bridge payload parsing."""

from __future__ import annotations

import json
import unittest

from torn_accessibility_hud.bridge.adapters import apply_bridge_update
from torn_accessibility_hud.bridge.payload import BridgeTableUpdate, GameStatePayload
from torn_accessibility_hud.models import GameSnapshot, RecommendedAction, Street, TableStateConfidence


class GameStatePayloadTests(unittest.TestCase):
    def test_parses_table_update(self) -> None:
        payload = GameStatePayload.from_json(
            json.dumps(
                {
                    "event": "table_update",
                    "pot": 18000,
                    "to_call": 120,
                    "hero_cards": ["Ah", "Kd"],
                    "board_cards": ["2s", "7h", "Jc"],
                    "hero_turn": True,
                    "legal_actions": ["fold", "call", "raise"],
                    "ts": 1718280000000,
                }
            )
        )
        self.assertEqual(payload.pot, 18000.0)
        self.assertEqual(payload.to_call, 120.0)
        self.assertEqual(payload.hero_cards, ("Ah", "Kd"))
        self.assertEqual(payload.board_cards, ("2s", "7h", "Jc"))
        self.assertTrue(payload.hero_turn)
        self.assertEqual(payload.legal_actions, ("fold", "call", "raise"))
        self.assertEqual(payload.street, Street.FLOP)

    def test_accepts_legacy_field_names(self) -> None:
        payload = GameStatePayload.from_json(
            json.dumps(
                {
                    "pot_amount": "18K",
                    "amount_to_call": "$120",
                    "hero_cards": ["AS", "KC"],
                    "board_cards": [],
                }
            )
        )
        self.assertEqual(payload.pot, 18000.0)
        self.assertEqual(payload.to_call, 120.0)
        self.assertEqual(payload.hero_cards, ("As", "Kc"))

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            GameStatePayload.from_json("{not json")


class BridgeAdapterTests(unittest.TestCase):
    def test_apply_bridge_update_bypasses_ocr_parsers(self) -> None:
        payload = GameStatePayload(
            pot=18000.0,
            to_call=120.0,
            hero_cards=("Ah", "Kd"),
            board_cards=("2s", "7h", "Jc"),
            hero_turn=True,
            legal_actions=("fold", "call", "raise"),
        )
        update = BridgeTableUpdate(payload=payload, received_at=0.0, sequence=1)
        snapshot = apply_bridge_update(GameSnapshot(), update)

        self.assertEqual(snapshot.pot_size, 18000.0)
        self.assertEqual(snapshot.to_call, 120.0)
        self.assertEqual(snapshot.hero_cards, ("Ah", "Kd"))
        self.assertEqual(snapshot.board_cards, ("2s", "7h", "Jc"))
        self.assertEqual(snapshot.street, Street.FLOP)
        self.assertEqual(snapshot.state_confidence, TableStateConfidence.HIGH)
        self.assertEqual(
            snapshot.legal_actions,
            (RecommendedAction.FOLD, RecommendedAction.CALL, RecommendedAction.RAISE),
        )
        assert snapshot.parse_diagnostics is not None
        self.assertEqual(snapshot.parse_diagnostics.pot_parsed, 18000.0)
        self.assertEqual(snapshot.parse_diagnostics.amount_to_call_parsed, 120.0)
        self.assertIsNone(snapshot.parse_diagnostics.block_reason)


if __name__ == "__main__":
    unittest.main()
