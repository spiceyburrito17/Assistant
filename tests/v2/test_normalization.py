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


if __name__ == "__main__":
    unittest.main()
