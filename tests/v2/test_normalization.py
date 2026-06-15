"""Tests for normalization layer."""

from __future__ import annotations

import unittest

from torn_hud_v2.models.messages import TableDeltaMessage
from torn_hud_v2.models.snapshot import Street
from torn_hud_v2.normalization.normalize import normalize_cards, normalize_message


class NormalizationTests(unittest.TestCase):
    def test_normalize_cards(self) -> None:
        self.assertEqual(normalize_cards(("Ah", "KD", "Ah")), ("Ah", "Kd"))

    def test_normalize_message_builds_snapshot(self) -> None:
        message = TableDeltaMessage(
            schema_version=1,
            message_type="table_delta",
            seq=1,
            ts_ms=1,
            pot_raw="$120",
            pot_parsed=120.0,
            hero_cards=("Ah", "Kd"),
            board_cards=("2s", "7h", "Jc"),
            hero_turn=True,
            legal_actions=("fold", "call", "raise"),
        )
        snapshot = normalize_message(message)
        self.assertEqual(snapshot.street, Street.FLOP)
        self.assertEqual(snapshot.pot.parsed, 120.0)

    def test_normalize_message_carries_extract_sources(self) -> None:
        message = TableDeltaMessage(
            schema_version=1,
            message_type="table_delta",
            seq=9,
            ts_ms=1,
            extract_sources="pot=text-anchor;hero=hand-face-up",
        )
        snapshot = normalize_message(message)
        self.assertEqual(snapshot.extract_sources, "pot=text-anchor;hero=hand-face-up")
        self.assertEqual(snapshot.seq, 9)

    def test_call_any_slot_becomes_check(self) -> None:
        message = TableDeltaMessage(
            schema_version=1,
            message_type="table_delta",
            seq=2,
            ts_ms=1,
            slot_left_raw="FOLD",
            slot_centre_raw="CALL ANY",
            slot_right_raw="RAISE TO $50",
            hero_turn=True,
        )
        snapshot = normalize_message(message)
        self.assertIn("check", snapshot.legal_actions_normalized)
        self.assertEqual(snapshot.amount_to_call.parsed, 0.0)


if __name__ == "__main__":
    unittest.main()
