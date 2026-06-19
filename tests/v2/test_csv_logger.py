"""Tests for v2 CSV logger reset and sanitization."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from torn_hud_v2.constants import CSV_COLUMNS, SessionEventType
from torn_hud_v2.debug.csv_logger import SessionCSVLogger
from torn_hud_v2.debug.sanitizer import sanitize_csv_cell


class CSVLoggerTests(unittest.TestCase):
    def test_reset_overwrites_existing_file_with_header_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.csv"
            path.write_text("stale,data\n1,2\n", encoding="utf-8")
            logger = SessionCSVLogger(path)
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(lines[0], ",".join(CSV_COLUMNS))
            self.assertEqual(len(lines), 1)

    def test_sanitize_multiline_text(self) -> None:
        self.assertEqual(sanitize_csv_cell("line1\nline2\r\nline3"), "line1 line2 line3")

    def test_logger_uses_shared_sanitizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.csv"
            logger = SessionCSVLogger(path)
            logger.log_row(
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "event_type": SessionEventType.HERO_TURN.value,
                    "hand_id": 1,
                    "street": "flop",
                    "hero_cards": "Ah|Kd",
                    "board_cards": "2s|7h|Jc",
                    "pot_raw": "POT:\n$120",
                    "pot_parsed": 120,
                    "slot_left_raw": "RAISE TO $240",
                    "slot_centre_raw": "CALL $120",
                    "slot_right_raw": "FOLD",
                    "post_hand_ui": False,
                    "amount_to_call_raw": "CALL $120",
                    "amount_to_call_parsed": 120,
                    "legal_actions_raw": "action_slot_centre='CALL $120'",
                    "legal_actions_normalized": "fold|call|raise",
                    "hero_turn": True,
                    "current_recommendation": "call",
                    "block_reason": "",
                    "state_confidence": "high",
                    "solver_status": "ok",
                    "hero_stack_raw": "$5,000",
                    "hero_stack_parsed": 5000,
                    "dom_seq": 42,
                    "extract_sources": "pot=text-anchor;hero=hand-face-up",
                }
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("POT: $120", text)
            self.assertNotIn("\nline2", text)


if __name__ == "__main__":
    unittest.main()
