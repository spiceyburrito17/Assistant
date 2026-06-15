"""Normalized table snapshot and recommendation view models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..models.provenance import FieldSource, SourcedValue


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    UNKNOWN = "unknown"


class StateConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class SolverStatus(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class RecommendedAction(str, Enum):
    WAIT = "wait"
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    BET = "bet"


@dataclass(frozen=True)
class TableSnapshot:
    """Backend source-of-truth snapshot after normalization and validation."""

    hand_id: int = 0
    street: Street = Street.UNKNOWN
    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()
    pot: SourcedValue[float] = field(default_factory=lambda: SourcedValue(None, None))
    hero_stack: SourcedValue[float] = field(default_factory=lambda: SourcedValue(None, None))
    amount_to_call: SourcedValue[float] = field(default_factory=lambda: SourcedValue(None, None))
    slot_left_raw: str = ""
    slot_centre_raw: str = ""
    slot_right_raw: str = ""
    legal_actions_raw: tuple[str, ...] = ()
    legal_actions_normalized: tuple[str, ...] = ()
    hero_turn: bool = False
    post_hand_ui: bool = False
    post_hand_labels: tuple[str, ...] = ()
    state_confidence: StateConfidence = StateConfidence.LOW
    block_reason: str | None = None
    generation: int = 0
    seq: int = 0
    extract_sources: str | None = None


@dataclass(frozen=True)
class RecommendationView:
    action: RecommendedAction = RecommendedAction.WAIT
    detail: str = "Waiting for table state."
    state_confidence: StateConfidence = StateConfidence.LOW
    solver_status: SolverStatus = SolverStatus.SKIPPED
    block_reason: str | None = None
