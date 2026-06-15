"""Single source of truth for stable CSV/event labels (v2)."""

from __future__ import annotations

from enum import Enum
from typing import Iterable

SCHEMA_VERSION = 1
DEFAULT_WS_HOST = "localhost"
DEFAULT_WS_PORT = 8765
DEFAULT_SESSION_CSV_PATH = "debug_captures/v2_current_session.csv"


class SessionEventType(str, Enum):
    """Stable event_type labels written to the v2 session CSV."""

    STREET_CHANGE = "street_change"
    HERO_TURN = "hero_turn"
    ACTIONS_UPDATE = "actions_update"
    DECISION = "decision"
    BLOCKED = "blocked"


SESSION_EVENT_PRIORITY: tuple[SessionEventType, ...] = (
    SessionEventType.STREET_CHANGE,
    SessionEventType.HERO_TURN,
    SessionEventType.ACTIONS_UPDATE,
    SessionEventType.DECISION,
    SessionEventType.BLOCKED,
)

SESSION_EVENT_TYPE_LABELS: tuple[str, ...] = tuple(event.value for event in SESSION_EVENT_PRIORITY)


CSV_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "event_type",
    "hand_id",
    "street",
    "hero_cards",
    "board_cards",
    "pot_raw",
    "pot_parsed",
    "slot_left_raw",
    "slot_centre_raw",
    "slot_right_raw",
    "post_hand_ui",
    "amount_to_call_raw",
    "amount_to_call_parsed",
    "legal_actions_raw",
    "legal_actions_normalized",
    "hero_turn",
    "current_recommendation",
    "block_reason",
    "state_confidence",
    "solver_status",
    "hero_stack_raw",
    "hero_stack_parsed",
    "dom_seq",
    "extract_sources",
)


def format_event_types(events: Iterable[SessionEventType]) -> str:
    """Return pipe-delimited event_type using only stable, ordered labels."""

    event_set = set(events)
    ordered = [event for event in SESSION_EVENT_PRIORITY if event in event_set]
    return "|".join(event.value for event in ordered)
