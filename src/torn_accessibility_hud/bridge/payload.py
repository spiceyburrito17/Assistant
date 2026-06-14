"""Validated table-state payloads received from the Tampermonkey bridge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..models import RecommendedAction, Street, TableParseDiagnostics, TableStateConfidence
_LEGAL_ACTIONS = frozenset(action.value for action in RecommendedAction if action is not RecommendedAction.WAIT)


def _normalize_card(raw: str) -> str | None:
    cleaned = raw.strip().upper().replace(" ", "")
    if cleaned.startswith("10") and len(cleaned) >= 3:
        cleaned = f"T{cleaned[-1]}"
    if len(cleaned) != 2:
        return None
    rank, suit = cleaned[0], cleaned[1].lower()
    if rank not in "23456789TJQKA" or suit not in "cdhs":
        return None
    return f"{rank}{suit}"


def _normalize_cards(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    cards: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        card = _normalize_card(item)
        if card is None or card in seen:
            continue
        cards.append(card)
        seen.add(card)
    return tuple(cards)


def _normalize_money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number >= 0 else None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "").upper()
        if not cleaned:
            return None
        multiplier = 1.0
        if cleaned.endswith("K"):
            multiplier = 1_000.0
            cleaned = cleaned[:-1]
        elif cleaned.endswith("M"):
            multiplier = 1_000_000.0
            cleaned = cleaned[:-1]
        try:
            number = float(cleaned) * multiplier
        except ValueError:
            return None
        return number if number >= 0 else None
    return None


def _normalize_legal_actions(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        label = item.strip().lower()
        if label not in _LEGAL_ACTIONS or label in seen:
            continue
        normalized.append(label)
        seen.add(label)
    return tuple(normalized)


def _street_from_board(board_cards: tuple[str, ...]) -> Street:
    if len(board_cards) >= 5:
        return Street.RIVER
    if len(board_cards) == 4:
        return Street.TURN
    if len(board_cards) == 3:
        return Street.FLOP
    return Street.PREFLOP


@dataclass(frozen=True)
class GameStatePayload:
    """Deterministic table state pushed by the browser userscript."""

    event: str = "table_update"
    pot: float | None = None
    to_call: float | None = None
    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()
    hero_turn: bool = False
    legal_actions: tuple[str, ...] = ()
    timestamp_ms: int | None = None
    source_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_json(cls, message: str | bytes) -> GameStatePayload:
        if isinstance(message, bytes):
            message = message.decode("utf-8", errors="replace")
        data = json.loads(message)
        if not isinstance(data, dict):
            raise ValueError("bridge payload must be a JSON object")

        event = str(data.get("event", "table_update"))
        pot = _normalize_money(data.get("pot", data.get("pot_amount")))
        to_call = _normalize_money(data.get("to_call", data.get("amount_to_call")))
        hero_cards = _normalize_cards(data.get("hero_cards", ()))
        board_cards = _normalize_cards(data.get("board_cards", ()))
        hero_turn = bool(data.get("hero_turn", False))
        legal_actions = _normalize_legal_actions(data.get("legal_actions", ()))

        timestamp_ms = data.get("ts", data.get("timestamp_ms"))
        if timestamp_ms is not None:
            timestamp_ms = int(timestamp_ms)

        return cls(
            event=event,
            pot=pot,
            to_call=to_call,
            hero_cards=hero_cards,
            board_cards=board_cards,
            hero_turn=hero_turn,
            legal_actions=legal_actions,
            timestamp_ms=timestamp_ms,
            source_url=data.get("source_url"),
            raw=data,
        )

    @property
    def street(self) -> Street:
        return _street_from_board(self.board_cards)

    def recommended_actions(self) -> tuple[RecommendedAction, ...]:
        return tuple(RecommendedAction(label) for label in self.legal_actions)

    def to_parse_diagnostics(self) -> TableParseDiagnostics:
        """Build diagnostics compatible with the existing HUD CSV/debug path."""

        return TableParseDiagnostics(
            pot_raw=str(int(self.pot)) if self.pot is not None else None,
            pot_parsed=self.pot,
            pot_normalized=self.pot,
            amount_to_call_parsed=self.to_call,
            legal_actions_normalized=self.legal_actions,
            legal_actions_raw=tuple(f"bridge={label!r}" for label in self.legal_actions),
            block_reason=None,
        )

    def fingerprint(self) -> tuple[Any, ...]:
        """Stable tuple for deduplicating unchanged payloads on the server."""

        return (
            self.event,
            self.pot,
            self.to_call,
            self.hero_cards,
            self.board_cards,
            self.hero_turn,
            self.legal_actions,
        )


@dataclass(frozen=True)
class BridgeTableUpdate:
    """Thread-safe queue item consumed by ``CoordinatorWorker`` (replaces ``OCRBatch``)."""

    payload: GameStatePayload
    received_at: float
    sequence: int

    @property
    def state_confidence(self) -> TableStateConfidence:
        if len(self.payload.hero_cards) == 2 and self.payload.pot is not None:
            return TableStateConfidence.HIGH
        return TableStateConfidence.LOW
