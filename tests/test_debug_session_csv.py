"""Tests for session debug CSV logging."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from torn_accessibility_hud.config import AppConfig
from torn_accessibility_hud.debug_session_csv import (
    CSV_COLUMNS,
    SESSION_DEBUG_EVENT_TYPE_LABELS,
    SessionDebugCSVLogger,
    SessionDebugEventTracker,
    SessionDebugEventType,
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
    def test_stable_event_type_labels(self) -> None:
        self.assertEqual(
            SESSION_DEBUG_EVENT_TYPE_LABELS,
            (
                SessionDebugEventType.STREET_CHANGE.value,
                SessionDebugEventType.HERO_TURN.value,
                SessionDebugEventType.ACTIONS_UPDATE.value,
                SessionDebugEventType.DECISION.value,
                SessionDebugEventType.BLOCKED.value,
            ),
        )

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
                event_type=SessionDebugEventType.HERO_TURN.value,
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
            self.assertEqual(rows[0]["event_type"], SessionDebugEventType.HERO_TURN.value)
            self.assertEqual(rows[0]["pot_raw"], "POT: $440")
            self.assertEqual(rows[0]["legal_actions_normalized"], "fold|call|raise")

    def test_csv_cell_sanitizes_multiline_and_whitespace(self) -> None:
        self.assertEqual(_csv_cell("line1\nline2"), "line1 line2")
        self.assertEqual(_csv_cell(True), "true")
        self.assertEqual(_csv_cell(10.0), "10")

    def test_tracker_logs_one_row_with_combined_event_types(self) -> None:
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
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_type"], "hero_turn|actions_update")

    def test_tracker_event_type_tokens_use_only_stable_labels(self) -> None:
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

            blocked = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                street=Street.FLOP,
                parse_diagnostics=TableParseDiagnostics(block_reason="pot_unreadable"),
            )
            tracker.observe(blocked, _make_recommendation(block_reason="pot_unreadable"))

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            for row in rows:
                for token in row["event_type"].split("|"):
                    self.assertIn(token, SESSION_DEBUG_EVENT_TYPE_LABELS)

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
            self.assertIn("street_change|decision", event_types)
            self.assertEqual(len(rows), 2)

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
            self.assertEqual(rows[0]["event_type"], SessionDebugEventType.BLOCKED.value)
            self.assertEqual(rows[0]["block_reason"], "pot_unreadable")

    def test_runtime_logger_sanitizes_fields_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            logger = SessionDebugCSVLogger(path)
            tracker = SessionDebugEventTracker(logger)

            snapshot = GameSnapshot(
                hero_cards=("Ah", "Kd"),
                street=Street.PREFLOP,
                legal_actions=(RecommendedAction.FOLD, RecommendedAction.CALL),
                parse_diagnostics=TableParseDiagnostics(
                    pot_crop_text="POT:\n$440",
                    legal_actions_raw=("FOLD", "CALL\n$10"),
                    legal_actions_normalized=("fold", "call"),
                ),
            )
            tracker.observe(snapshot, _make_recommendation())

            with path.open("r", encoding="utf-8", newline="") as fp:
                rows = list(csv.DictReader(fp))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pot_raw"], "POT: $440")
            self.assertEqual(rows[0]["legal_actions_raw"], "FOLD|CALL $10")
            for value in rows[0].values():
                self.assertNotIn("\n", value)
                self.assertNotIn("\r", value)

    def test_engine_restart_clears_stale_rows_via_logger_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "debug_current_session.csv"
            path.write_text("stale,data\n1,2\n", encoding="utf-8")

            first_run = SessionDebugCSVLogger(path)
            first_run.log_debug_state(
                timestamp="2026-06-13T12:00:00.000+00:00",
                event_type=SessionDebugEventType.HERO_TURN.value,
                hand_id=1,
                street="preflop",
                hero_cards="Ah|Kd",
                board_cards="",
                pot_raw="POT: $440",
                pot_parsed=440,
                fold_button_raw="FOLD",
                call_button_raw="CALL $10",
                raise_button_raw="",
                amount_to_call_raw="CALL $10",
                amount_to_call_parsed=10,
                legal_actions_raw="FOLD|CALL $10",
                legal_actions_normalized="fold|call",
                hero_turn=True,
                current_recommendation="wait",
                block_reason="",
                state_confidence="high",
                solver_status="skipped",
            )
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)

            SessionDebugCSVLogger(path)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0], ",".join(CSV_COLUMNS))

    def test_default_config_path_matches_production_logger(self) -> None:
        config = AppConfig.default()
        self.assertEqual(
            config.debug.session_csv_path,
            "debug_captures/debug_current_session.csv",
        )
        self.assertTrue(config.debug.session_csv_enabled)


if __name__ == "__main__":
    unittest.main()
