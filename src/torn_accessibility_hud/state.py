"""State smoothing helpers for volatile vision results."""

from __future__ import annotations

from dataclasses import replace

from .diagnostics import debug_log
from .models import ActionType, GameSnapshot, ParsedEvent


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
