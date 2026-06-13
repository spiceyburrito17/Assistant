"""State smoothing helpers for volatile vision results."""

from __future__ import annotations

from dataclasses import replace

from .diagnostics import debug_log
from .models import ActionType, GameSnapshot, ParsedEvent


class StickyCardCache:
    """Keep last-good card reads through short OCR dropouts."""

    def __init__(self, max_missing_frames: int = 15) -> None:
        self.max_missing_frames = max_missing_frames
        self.cached_hero_cards: tuple[str, ...] = ()
        self.cached_board_cards: tuple[str, ...] = ()
        self.hero_missing_frames = 0
        self.board_missing_frames = 0

    def apply(self, snapshot: GameSnapshot, events: tuple[ParsedEvent, ...]) -> tuple[GameSnapshot, bool]:
        original = snapshot
        hero_event = self._latest_hero_event(events)
        board_event = self._latest_board_event(events)

        if hero_event is not None and len(hero_event.cards) == 2:
            if hero_event.cards != self.cached_hero_cards:
                debug_log("[CACHE] locked hero cards %s", list(hero_event.cards))
                self.cached_board_cards = ()
                self.board_missing_frames = 0
            self.cached_hero_cards = hero_event.cards
            self.hero_missing_frames = 0
        else:
            snapshot = self._apply_missing_hero(snapshot)

        if board_event is not None and len(board_event.cards) in {3, 4, 5}:
            if board_event.cards != self.cached_board_cards:
                debug_log("[CACHE] locked board cards %s", list(board_event.cards))
            self.cached_board_cards = board_event.cards
            self.board_missing_frames = 0
        else:
            snapshot = self._apply_missing_board(snapshot)

        return snapshot, snapshot != original

    def _apply_missing_hero(self, snapshot: GameSnapshot) -> GameSnapshot:
        if not self.cached_hero_cards:
            return snapshot
        self.hero_missing_frames += 1
        if self.hero_missing_frames > self.max_missing_frames:
            debug_log("[CACHE] clearing hero cards after %s missing frames", self.hero_missing_frames)
            self.cached_hero_cards = ()
            self.cached_board_cards = ()
            self.board_missing_frames = 0
            if snapshot.hero_cards or snapshot.board_cards:
                return replace(snapshot, hero_cards=(), board_cards=(), generation=snapshot.generation + 1)
            return snapshot
        debug_log("[CACHE] OCR missed hero card, using cached %s", list(self.cached_hero_cards))
        if snapshot.hero_cards != self.cached_hero_cards:
            return replace(snapshot, hero_cards=self.cached_hero_cards, generation=snapshot.generation + 1)
        return snapshot

    def _apply_missing_board(self, snapshot: GameSnapshot) -> GameSnapshot:
        if not self.cached_board_cards:
            return snapshot
        self.board_missing_frames += 1
        if self.board_missing_frames > self.max_missing_frames:
            debug_log("[CACHE] clearing board cards after %s missing frames", self.board_missing_frames)
            self.cached_board_cards = ()
            if snapshot.board_cards:
                return replace(snapshot, board_cards=(), generation=snapshot.generation + 1)
            return snapshot
        debug_log("[CACHE] OCR missed board card, using cached %s", list(self.cached_board_cards))
        if snapshot.board_cards != self.cached_board_cards:
            return replace(snapshot, board_cards=self.cached_board_cards, generation=snapshot.generation + 1)
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
