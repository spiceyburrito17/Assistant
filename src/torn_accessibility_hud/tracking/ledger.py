"""Real-time opponent action ledger and public stats."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import ActionType, ParsedEvent, PlayerStats, Street
from .range_matrix import RangeMatrix


@dataclass
class OpponentRecord:
    player_name: str
    hands_seen: int = 0
    vpip_count: int = 0
    pfr_count: int = 0
    last_action: str = "none"
    range_matrix: RangeMatrix = field(default_factory=RangeMatrix)
    _seen_in_current_hand: bool = False
    _vpip_in_current_hand: bool = False
    _pfr_in_current_hand: bool = False

    @property
    def vpip(self) -> float:
        return self.vpip_count / self.hands_seen if self.hands_seen else 0.0

    @property
    def pfr(self) -> float:
        return self.pfr_count / self.hands_seen if self.hands_seen else 0.0

    def begin_hand(self) -> None:
        self._seen_in_current_hand = False
        self._vpip_in_current_hand = False
        self._pfr_in_current_hand = False
        self.last_action = "none"
        self.range_matrix = RangeMatrix()

    def observe_action(self, action: ActionType, street: Street, amount: float | None) -> None:
        if not self._seen_in_current_hand:
            self.hands_seen += 1
            self._seen_in_current_hand = True
        if street is Street.PREFLOP and action in {ActionType.CALL, ActionType.BET, ActionType.RAISE, ActionType.ALL_IN}:
            if not self._vpip_in_current_hand:
                self.vpip_count += 1
                self._vpip_in_current_hand = True
        if street is Street.PREFLOP and action in {ActionType.RAISE, ActionType.BET, ActionType.ALL_IN}:
            if not self._pfr_in_current_hand:
                self.pfr_count += 1
                self._pfr_in_current_hand = True
        self.last_action = action.value
        self.range_matrix.apply_action(action, street, amount)

    def to_public_stats(self) -> PlayerStats:
        return PlayerStats(
            player_name=self.player_name,
            hands_seen=self.hands_seen,
            vpip=self.vpip,
            pfr=self.pfr,
            last_action=self.last_action,
            top_range_classes=self.range_matrix.top_classes(limit=6),
        )


class OpponentLedger:
    """Tracks opponents and produces immutable snapshots for UI/equity."""

    def __init__(self) -> None:
        self.records: dict[str, OpponentRecord] = {}
        self.current_street = Street.PREFLOP
        self.active_opponents: set[str] = set()

    def begin_hand(self) -> None:
        self.current_street = Street.PREFLOP
        self.active_opponents.clear()
        for record in self.records.values():
            record.begin_hand()

    def process_events(self, events: tuple[ParsedEvent, ...]) -> None:
        for event in events:
            self.process_event(event)

    def process_event(self, event: ParsedEvent) -> None:
        if event.action is ActionType.DEALT_HERO:
            self.begin_hand()
            return
        if event.action is ActionType.BOARD and event.street is not None:
            self.current_street = event.street
            return
        if event.player_name is None:
            return
        if event.action is ActionType.UNKNOWN:
            return
        record = self.records.setdefault(event.player_name, OpponentRecord(player_name=event.player_name))
        street = event.street or self.current_street
        record.observe_action(event.action, street, event.amount)
        if event.action is ActionType.FOLD:
            self.active_opponents.discard(event.player_name)
        elif event.action is not ActionType.POST_BLIND:
            self.active_opponents.add(event.player_name)

    def public_stats(self) -> tuple[PlayerStats, ...]:
        return tuple(
            record.to_public_stats()
            for record in sorted(self.records.values(), key=lambda item: item.player_name.lower())
        )

    def range_weight_snapshot(self) -> dict[str, dict[str, float]]:
        return {
            name: self.records[name].range_matrix.copy_weights()
            for name in sorted(self.active_opponents)
            if name in self.records
        }
