"""Event-driven state machine for DOM-first table updates."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..constants import SessionEventType, format_event_types
from ..debug.csv_logger import SessionCSVLogger
from ..debug.sanitizer import join_csv_values
from ..models.snapshot import RecommendationView, TableSnapshot


@dataclass
class StateMachineContext:
    hand_id: int = 0
    last_street: str | None = None
    last_hero_turn: bool = False
    last_legal_actions: tuple[str, ...] = ()
    last_recommendation: str | None = None
    last_block_reason: str | None = None


@dataclass
class StateTransitionResult:
    snapshot: TableSnapshot
    events: set[SessionEventType] = field(default_factory=set)
    recommendation: RecommendationView | None = None


class TableStateMachine:
    """Detect meaningful transitions and emit stable debug events."""

    def __init__(self, csv_logger: SessionCSVLogger) -> None:
        self.csv_logger = csv_logger
        self.context = StateMachineContext()

    def apply(
        self,
        snapshot: TableSnapshot,
        recommendation: RecommendationView,
    ) -> StateTransitionResult:
        events = self._detect_events(snapshot, recommendation)
        if events:
            self._write_csv_row(snapshot, recommendation, events)
        self._update_context(snapshot, recommendation)
        return StateTransitionResult(snapshot=snapshot, events=events, recommendation=recommendation)

    def _detect_events(
        self,
        snapshot: TableSnapshot,
        recommendation: RecommendationView,
    ) -> set[SessionEventType]:
        events: set[SessionEventType] = set()

        if snapshot.hand_id != self.context.hand_id and snapshot.hero_cards:
            self.context.hand_id = snapshot.hand_id

        street = snapshot.street.value
        if self.context.last_street is not None and street != self.context.last_street:
            events.add(SessionEventType.STREET_CHANGE)

        if snapshot.hero_turn and not self.context.last_hero_turn:
            events.add(SessionEventType.HERO_TURN)

        if snapshot.legal_actions_normalized != self.context.last_legal_actions:
            events.add(SessionEventType.ACTIONS_UPDATE)

        recommendation_action = recommendation.action.value
        if (
            recommendation_action != "wait"
            and recommendation_action != self.context.last_recommendation
        ):
            events.add(SessionEventType.DECISION)

        block_reason = recommendation.block_reason or snapshot.block_reason
        if block_reason and block_reason != self.context.last_block_reason:
            events.add(SessionEventType.BLOCKED)

        return events

    def _write_csv_row(
        self,
        snapshot: TableSnapshot,
        recommendation: RecommendationView,
        events: set[SessionEventType],
    ) -> None:
        from datetime import datetime, timezone

        self.csv_logger.log_row(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "event_type": format_event_types(events),
                "hand_id": snapshot.hand_id,
                "street": snapshot.street.value,
                "hero_cards": join_csv_values(snapshot.hero_cards),
                "board_cards": join_csv_values(snapshot.board_cards),
                "pot_raw": snapshot.pot.raw or "",
                "pot_parsed": snapshot.pot.parsed if snapshot.pot.parsed is not None else "",
                "slot_left_raw": snapshot.slot_left_raw,
                "slot_centre_raw": snapshot.slot_centre_raw,
                "slot_right_raw": snapshot.slot_right_raw,
                "post_hand_ui": snapshot.post_hand_ui,
                "amount_to_call_raw": snapshot.amount_to_call.raw or "",
                "amount_to_call_parsed": (
                    snapshot.amount_to_call.parsed if snapshot.amount_to_call.parsed is not None else ""
                ),
                "legal_actions_raw": join_csv_values(snapshot.legal_actions_raw),
                "legal_actions_normalized": join_csv_values(snapshot.legal_actions_normalized),
                "hero_turn": snapshot.hero_turn,
                "current_recommendation": recommendation.action.value,
                "block_reason": recommendation.block_reason or snapshot.block_reason or "",
                "state_confidence": recommendation.state_confidence.value,
                "solver_status": recommendation.solver_status.value,
                "hero_stack_raw": snapshot.hero_stack.raw or "",
                "hero_stack_parsed": (
                    snapshot.hero_stack.parsed if snapshot.hero_stack.parsed is not None else ""
                ),
                "dom_seq": snapshot.seq,
                "extract_sources": snapshot.extract_sources or "",
            }
        )

    def _update_context(self, snapshot: TableSnapshot, recommendation: RecommendationView) -> None:
        self.context.hand_id = snapshot.hand_id
        self.context.last_street = snapshot.street.value
        self.context.last_hero_turn = snapshot.hero_turn
        self.context.last_legal_actions = snapshot.legal_actions_normalized
        self.context.last_recommendation = recommendation.action.value
        self.context.last_block_reason = recommendation.block_reason or snapshot.block_reason
