"""Tests for v2 state machine transitions."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from torn_hud_v2.constants import SessionEventType
from torn_hud_v2.debug.csv_logger import SessionCSVLogger
from torn_hud_v2.models.provenance import SourcedValue
from torn_hud_v2.models.snapshot import (
    RecommendationView,
    RecommendedAction,
    SolverStatus,
    StateConfidence,
    Street,
    TableSnapshot,
)
from torn_hud_v2.state.machine import TableStateMachine


def _snapshot(**overrides: object) -> TableSnapshot:
    base = {
        "hand_id": 1,
        "street": Street.FLOP,
        "hero_cards": ("Ah", "Kd"),
        "board_cards": ("2s", "7h", "Jc"),
        "pot": SourcedValue(raw="$120", parsed=120.0),
        "amount_to_call": SourcedValue(raw="CALL $20", parsed=20.0),
        "legal_actions_normalized": ("fold", "call", "raise"),
        "hero_turn": True,
        "state_confidence": StateConfidence.HIGH,
        "generation": 1,
    }
    base.update(overrides)
    return TableSnapshot(**base)


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.logger = SessionCSVLogger(Path(self.tmp.name) / "session.csv")
        self.machine = TableStateMachine(self.logger)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_emits_hero_turn_and_actions_update(self) -> None:
        snap = _snapshot()
        rec = RecommendationView(
            action=RecommendedAction.CALL,
            detail="stub",
            state_confidence=StateConfidence.HIGH,
            solver_status=SolverStatus.OK,
        )
        result = self.machine.apply(snap, rec)
        self.assertIn(SessionEventType.HERO_TURN, result.events)
        self.assertIn(SessionEventType.ACTIONS_UPDATE, result.events)

    def test_emits_street_change(self) -> None:
        first = _snapshot(street=Street.FLOP)
        second = _snapshot(street=Street.TURN, board_cards=("2s", "7h", "Jc", "Td"), generation=2)
        rec = RecommendationView(action=RecommendedAction.WAIT, solver_status=SolverStatus.SKIPPED)
        self.machine.apply(first, rec)
        result = self.machine.apply(second, rec)
        self.assertIn(SessionEventType.STREET_CHANGE, result.events)


if __name__ == "__main__":
    unittest.main()
