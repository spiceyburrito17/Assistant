"""State smoothing helpers for volatile vision results."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from .diagnostics import debug_log
from .models import (
    ActionType,
    GameSnapshot,
    ParsedEvent,
    RecommendedAction,
    Street,
    TableStateConfidence,
)
from .parsing.legal_actions import parse_legal_actions_from_lines


class CardReadStabilizer:
    """Require consecutive identical card reads before publishing OCR events."""

    def __init__(self, stable_reads_required: int = 3) -> None:
        self.stable_reads_required = max(stable_reads_required, 1)
        self._pending: dict[str, tuple[str, ...]] = {}
        self._streak: dict[str, int] = {}
        self._published: dict[str, tuple[str, ...]] = {}

    def observe(self, region: str, detected_cards: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Return a newly confirmed card tuple to publish, or None to keep the last stable read."""

        if not detected_cards:
            self._streak[region] = 0
            self._pending.pop(region, None)
            return None
        if detected_cards == self._pending.get(region):
            self._streak[region] = self._streak.get(region, 0) + 1
        else:
            self._pending[region] = detected_cards
            self._streak[region] = 1
        if (
            self._streak[region] >= self.stable_reads_required
            and detected_cards != self._published.get(region)
        ):
            self._published[region] = detected_cards
            debug_log(
                "[STABLE] confirmed %s after %s reads: %s",
                region,
                self._streak[region],
                list(detected_cards),
            )
            return detected_cards
        return None

    def published(self, region: str) -> tuple[str, ...]:
        return self._published.get(region, ())


class StickyCardCache:
    """Keep last-good card reads through short OCR dropouts."""

    def __init__(self, max_missing_scans: int = 12) -> None:
        self.max_missing_scans = max_missing_scans
        self.cached_hero_cards: tuple[str, ...] = ()
        self.cached_board_cards: tuple[str, ...] = ()
        self.hero_missing_scans = 0
        self.board_missing_scans = 0

    def apply(
        self,
        snapshot: GameSnapshot,
        events: tuple[ParsedEvent, ...],
        hero_region_folded: bool = False,
        hero_cards_scanned: bool = False,
        board_cards_scanned: bool = False,
    ) -> tuple[GameSnapshot, bool]:
        original = snapshot
        hero_event = self._latest_hero_event(events)
        board_event = self._latest_board_event(events)

        if hero_event is not None and len(hero_event.cards) == 2:
            if hero_event.cards != self.cached_hero_cards:
                debug_log("[CACHE] locked hero cards %s", list(hero_event.cards))
                self.cached_board_cards = ()
                self.board_missing_scans = 0
            self.cached_hero_cards = hero_event.cards
            self.hero_missing_scans = 0
        elif hero_region_folded and self.cached_hero_cards:
            debug_log("[CACHE] hero region folded/greyed; preserving cached %s", list(self.cached_hero_cards))
            self.hero_missing_scans = 0
            if snapshot.hero_cards != self.cached_hero_cards:
                snapshot = replace(snapshot, hero_cards=self.cached_hero_cards)
        elif hero_cards_scanned:
            snapshot = self._apply_missing_hero(snapshot)
        elif self.cached_hero_cards and snapshot.hero_cards != self.cached_hero_cards:
            snapshot = replace(snapshot, hero_cards=self.cached_hero_cards)

        if board_event is not None and len(board_event.cards) in {3, 4, 5}:
            if board_event.cards != self.cached_board_cards:
                debug_log("[CACHE] locked board cards %s", list(board_event.cards))
            self.cached_board_cards = board_event.cards
            self.board_missing_scans = 0
        elif board_cards_scanned:
            snapshot = self._apply_missing_board(snapshot)
        elif self.cached_board_cards and snapshot.board_cards != self.cached_board_cards:
            snapshot = replace(snapshot, board_cards=self.cached_board_cards)

        return snapshot, snapshot != original

    def _apply_missing_hero(self, snapshot: GameSnapshot) -> GameSnapshot:
        if not self.cached_hero_cards:
            return snapshot
        self.hero_missing_scans += 1
        if self.hero_missing_scans > self.max_missing_scans:
            debug_log("[CACHE] clearing hero cards after %s missed scans", self.hero_missing_scans)
            self.cached_hero_cards = ()
            self.cached_board_cards = ()
            self.board_missing_scans = 0
            if snapshot.hero_cards or snapshot.board_cards:
                return replace(
                    snapshot,
                    hero_cards=(),
                    board_cards=(),
                    generation=snapshot.generation + 1,
                )
            return snapshot
        debug_log("[CACHE] OCR missed hero card, using cached %s", list(self.cached_hero_cards))
        if snapshot.hero_cards != self.cached_hero_cards:
            return replace(snapshot, hero_cards=self.cached_hero_cards)
        return snapshot

    def _apply_missing_board(self, snapshot: GameSnapshot) -> GameSnapshot:
        if not self.cached_board_cards:
            return snapshot
        self.board_missing_scans += 1
        if self.board_missing_scans > self.max_missing_scans:
            debug_log("[CACHE] clearing board cards after %s missed scans", self.board_missing_scans)
            self.cached_board_cards = ()
            if snapshot.board_cards:
                return replace(snapshot, board_cards=(), generation=snapshot.generation + 1)
            return snapshot
        debug_log("[CACHE] OCR missed board card, using cached %s", list(self.cached_board_cards))
        if snapshot.board_cards != self.cached_board_cards:
            return replace(snapshot, board_cards=self.cached_board_cards)
        return snapshot

    @staticmethod
    def _latest_hero_event(events: tuple[ParsedEvent, ...]) -> ParsedEvent | None:
        for event in reversed(events):
            if event.action is ActionType.DEALT_HERO:
                return event
        return None

    @staticmethod
    def _latest_board_event(events: tuple[ParsedEvent, ...]) -> ParsedEvent | None:
        for event in reversed(events):
            if event.action is ActionType.BOARD:
                return event
        return None


@dataclass(frozen=True)
class TrustedTableState:
    """Last stable view of table facts used by equity and decisions."""

    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()
    pot_size: float | None = None
    to_call: float | None = None
    street: Street = Street.PREFLOP
    legal_actions: tuple[RecommendedAction, ...] = ()
    generation: int = 0
    updated_at: float = 0.0
    state_confidence: TableStateConfidence = TableStateConfidence.LOW

    def to_snapshot(self, raw: GameSnapshot) -> GameSnapshot:
        return replace(
            raw,
            hero_cards=self.hero_cards,
            board_cards=self.board_cards,
            pot_size=self.pot_size if self.pot_size is not None else raw.pot_size,
            to_call=self.to_call if self.to_call is not None else raw.to_call,
            street=self.street,
            legal_actions=self.legal_actions,
            state_confidence=self.state_confidence,
            generation=self.generation,
        )


@dataclass
class TrustedTableStateManager:
    """Apply OCR hysteresis so transient misses do not flash the HUD."""

    hero_missing_grace_scans: int = 12
    board_regress_scans: int = 8
    legal_actions_grace_sec: float = 2.0

    def __post_init__(self) -> None:
        self._trusted = TrustedTableState()
        self._hero_missing_scans = 0
        self._board_missing_scans = 0
        self._legal_actions_seen_at = 0.0

    @property
    def trusted(self) -> TrustedTableState:
        return self._trusted

    def apply(
        self,
        raw: GameSnapshot,
        events: tuple[ParsedEvent, ...],
        ocr_lines: tuple[str, ...],
        *,
        hero_cards_scanned: bool = False,
        board_cards_scanned: bool = False,
        hero_region_folded: bool = False,
    ) -> tuple[TrustedTableState, GameSnapshot]:
        now = time.monotonic()
        hero_cards = self._trusted.hero_cards
        board_cards = self._trusted.board_cards
        pot_size = self._trusted.pot_size
        to_call = self._trusted.to_call
        street = self._trusted.street
        generation = self._trusted.generation

        hero_event = self._latest_event(events, ActionType.DEALT_HERO)
        board_event = self._latest_event(events, ActionType.BOARD)

        if hero_event is not None and len(hero_event.cards) == 2:
            if hero_event.cards != hero_cards:
                debug_log("[TRUST] new hero hand %s", list(hero_event.cards))
                board_cards = ()
                pot_size = None
                to_call = None
                street = Street.PREFLOP
                generation += 1
            hero_cards = hero_event.cards
            self._hero_missing_scans = 0
        elif hero_region_folded and hero_cards:
            self._hero_missing_scans = 0
        elif hero_cards_scanned:
            self._hero_missing_scans += 1
            if self._hero_missing_scans > self.hero_missing_grace_scans:
                debug_log("[TRUST] clearing hero after %s missed scans", self._hero_missing_scans)
                hero_cards = ()
                board_cards = ()
                pot_size = None
                to_call = None
                generation += 1
        elif hero_cards and raw.hero_cards != hero_cards:
            hero_cards = hero_cards
        elif len(raw.hero_cards) == 2 and not hero_cards:
            hero_cards = raw.hero_cards
            self._hero_missing_scans = 0

        if board_event is not None and len(board_event.cards) in {3, 4, 5}:
            if board_event.cards != board_cards:
                debug_log("[TRUST] board updated %s", list(board_event.cards))
            board_cards = board_event.cards
            street = board_event.street or self._street_from_board(board_cards)
            self._board_missing_scans = 0
        elif board_cards_scanned:
            self._board_missing_scans += 1
            if self._board_missing_scans > self.board_regress_scans:
                debug_log("[TRUST] clearing board after %s missed scans", self._board_missing_scans)
                board_cards = ()
                street = Street.PREFLOP if not hero_cards else street
        elif board_cards and raw.board_cards != board_cards:
            board_cards = board_cards
        elif len(raw.board_cards) >= 3 and not board_cards:
            board_cards = raw.board_cards[:5]
            street = self._street_from_board(board_cards)
            self._board_missing_scans = 0

        for event in events:
            if event.action is not ActionType.POT or event.amount is None:
                continue
            if event.raw_text.lower().startswith("to_call"):
                to_call = max(0.0, event.amount)
            elif event.amount > 0:
                pot_size = event.amount

        parsed_actions = parse_legal_actions_from_lines(ocr_lines)
        if parsed_actions:
            legal_actions = parsed_actions
            self._legal_actions_seen_at = now
        elif self._legal_actions_seen_at > 0.0 and now - self._legal_actions_seen_at <= self.legal_actions_grace_sec:
            legal_actions = self._trusted.legal_actions
        else:
            legal_actions = ()

        if raw.pot_size > 0:
            pot_size = raw.pot_size
        if raw.to_call > 0:
            to_call = raw.to_call
        elif any(
            event.action is ActionType.POT and event.raw_text.lower().startswith("to_call")
            for event in events
        ):
            to_call = max(0.0, raw.to_call)
        elif to_call is None and raw.to_call == 0 and (
            RecommendedAction.CHECK in legal_actions or RecommendedAction.CALL in legal_actions
        ):
            to_call = 0.0

        if board_cards:
            street = self._street_from_board(board_cards)
        elif hero_cards and not board_cards:
            street = Street.PREFLOP

        confidence, _notes = self._assess_confidence(
            hero_cards=hero_cards,
            board_cards=board_cards,
            pot_size=pot_size,
            to_call=to_call,
            street=street,
            legal_actions=legal_actions,
        )
        self._trusted = TrustedTableState(
            hero_cards=hero_cards,
            board_cards=board_cards,
            pot_size=pot_size,
            to_call=to_call,
            street=street,
            legal_actions=legal_actions,
            generation=generation,
            updated_at=now,
            state_confidence=confidence,
        )
        return self._trusted, self._trusted.to_snapshot(raw)

    @staticmethod
    def _street_from_board(board_cards: tuple[str, ...]) -> Street:
        if len(board_cards) >= 5:
            return Street.RIVER
        if len(board_cards) == 4:
            return Street.TURN
        if len(board_cards) == 3:
            return Street.FLOP
        return Street.PREFLOP

    @staticmethod
    def _assess_confidence(
        hero_cards: tuple[str, ...],
        board_cards: tuple[str, ...],
        pot_size: float | None,
        to_call: float | None,
        street: Street,
        legal_actions: tuple[RecommendedAction, ...],
    ) -> tuple[TableStateConfidence, tuple[str, ...]]:
        notes: list[str] = []
        if len(hero_cards) != 2:
            notes.append("hero cards missing")
        if street is not Street.PREFLOP and len(board_cards) < 3:
            notes.append("board cards missing for street")
        if pot_size is None or pot_size <= 0:
            notes.append("pot unreadable")
        if to_call is None:
            notes.append("call amount missing")
        if not legal_actions:
            notes.append("legal actions missing")
        if notes:
            return TableStateConfidence.LOW, tuple(notes)
        return TableStateConfidence.HIGH, ()

    @staticmethod
    def _latest_event(events: tuple[ParsedEvent, ...], action: ActionType) -> ParsedEvent | None:
        for event in reversed(events):
            if event.action is action:
                return event
        return None
