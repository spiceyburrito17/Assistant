"""Tests for session debug CSV logging."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from torn_accessibility_hud.debug_session_csv import (
    CSV_COLUMNS,
    SessionDebugCSVLogger,
    SessionDebugEventTracker,
    _csv_cell,
)
from torn_accessibility_hud.models import (
    GameSnapshot,
    Recommendation,
    RecommendationLevel,
    RecommendedAction,
    SolverStatus,
    Street,
    TableParseDiagnostics,
    TableStateConfidence,
)


def _make_recommendation(
    *,
    action: RecommendedAction = RecommendedAction.WAIT,
    block_reason: str | None = None,
) -> Recommendation:
    return Recommendation(
        level=RecommendationLevel.WAIT,
        title="Wait",
        detail="Waiting",
        color_hex="#888888",
        action=action,
        solver_status=SolverStatus.SKIPPED,
        decision_blocked_reason=block_reason,
    )


class SessionDebugCSVTests(unittest.TestCase):
    def test_reset_overwrites_existing_file_with_header_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            path.write_text("old,data\n1,2\n", encoding="utf-8")

            logger = SessionDebugCSVLogger(path)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], ",".join(CSV_COLUMNS))

    def test_log_debug_state_writes_csv_safe_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            logger = SessionDebugCSVLogger(path)
            logger.log_debug_state(
                timestamp="2026-06-13T12:00:00.000+00:00",
                event_type="hero_turn",
                hand_id=1,
                street="preflop",
                hero_cards="Ah|Kd",
                board_cards="",
                pot_raw="POT: $440",
                pot_parsed=440,
                fold_button_raw="FOLD",
                call_button_raw="CALL $10",
                raise_button_raw="RAISE TO $20",
                amount_to_call_raw="CALL $10",
                amount_to_call_parsed=10,
                legal_actions_raw="FOLD|CALL $10|RAISE TO $20",
                legal_actions_normalized="fold|call|raise",
                hero_turn=True,
                current_recommendation="call",
                block_reason="",
                state_confidence="high",
                solver_status="skipped",
            )

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_type"], "hero_turn")
            self.assertEqual(rows[0]["pot_raw"], "POT: $440")
            self.assertEqual(rows[0]["legal_actions_normalized"], "fold|call|raise")

    def test_csv_cell_sanitizes_multiline_and_whitespace(self) -> None:
        self.assertEqual(_csv_cell("line1\nline2"), "line1 line2")
        self.assertEqual(_csv_cell(True), "true")
        self.assertEqual(_csv_cell(10.0), "10")

    def test_tracker_logs_only_on_meaningful_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            logger = SessionDebugCSVLogger(path)
            tracker = SessionDebugEventTracker(logger)

            base_snapshot = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                street=Street.PREFLOP,
                legal_actions=(RecommendedAction.FOLD, RecommendedAction.CALL),
                parse_diagnostics=TableParseDiagnostics(
                    legal_actions_raw=("FOLD", "CALL $10"),
                    legal_actions_normalized=("fold", "call"),
                    amount_to_call_parsed=10.0,
                ),
            )
            recommendation = _make_recommendation()

            tracker.observe(base_snapshot, recommendation)
            tracker.observe(base_snapshot, recommendation)

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 2)
            event_types = {row["event_type"] for row in rows}
            self.assertEqual(event_types, {"hero_turn", "actions_update"})

    def test_tracker_emits_street_change_and_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            logger = SessionDebugCSVLogger(path)
            tracker = SessionDebugEventTracker(logger)

            preflop = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                street=Street.PREFLOP,
                legal_actions=(RecommendedAction.FOLD, RecommendedAction.CHECK),
                parse_diagnostics=TableParseDiagnostics(
                    legal_actions_normalized=("fold", "check"),
                ),
            )
            tracker.observe(preflop, _make_recommendation())

            flop = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                board_cards=("2c", "3d", "4h"),
                street=Street.FLOP,
                legal_actions=(RecommendedAction.FOLD, RecommendedAction.CHECK),
                parse_diagnostics=TableParseDiagnostics(
                    legal_actions_normalized=("fold", "check"),
                ),
            )
            tracker.observe(flop, _make_recommendation(action=RecommendedAction.CHECK))

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            event_types = [row["event_type"] for row in rows]
            self.assertIn("street_change", event_types)
            self.assertIn("decision", event_types)

    def test_tracker_emits_blocked_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            logger = SessionDebugCSVLogger(path)
            tracker = SessionDebugEventTracker(logger)

            snapshot = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                street=Street.PREFLOP,
                state_confidence=TableStateConfidence.LOW,
                parse_diagnostics=TableParseDiagnostics(block_reason="pot_unreadable"),
            )
            recommendation = _make_recommendation(block_reason="pot_unreadable")
            tracker.observe(snapshot, recommendation)

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_type"], "blocked")
            self.assertEqual(rows[0]["block_reason"], "pot_unreadable")


if __name__ == "__main__":
    unittest.main()
