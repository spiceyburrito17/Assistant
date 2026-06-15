"""Convert raw userscript payloads into normalized backend snapshots."""

from __future__ import annotations

import re

from .action_slots import amount_to_call_from_slots, legal_actions_from_slots
from ..models.messages import TableDeltaMessage
from ..models.provenance import FieldSource, SourcedValue
from ..models.snapshot import StateConfidence, Street, TableSnapshot

_CARD_RE = re.compile(r"^([2-9TJQKA]|10)([cdhs])$", re.IGNORECASE)
_ACTION_LABELS = frozenset({"fold", "check", "call", "raise", "bet"})


def normalize_cards(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        card = _normalize_card(raw)
        if card is None or card in seen:
            continue
        normalized.append(card)
        seen.add(card)
    return tuple(normalized)


def normalize_money(raw: str | None, parsed: float | None) -> SourcedValue[float]:
    if parsed is not None and parsed >= 0:
        return SourcedValue(raw=raw, parsed=float(parsed), source=FieldSource.DOM)
    if raw:
        inferred = _parse_money_text(raw)
        if inferred is not None:
            return SourcedValue(raw=raw, parsed=inferred, source=FieldSource.INFERRED)
    return SourcedValue(raw=raw, parsed=None, source=FieldSource.DOM)


def normalize_actions(raw_slots: tuple[str, ...], explicit: tuple[str, ...]) -> tuple[str, ...]:
    if explicit:
        return tuple(label for label in explicit if label in _ACTION_LABELS)
    labels: list[str] = []
    seen: set[str] = set()
    for text in raw_slots:
        for label in _labels_from_slot_text(text):
            if label not in seen:
                labels.append(label)
                seen.add(label)
    return tuple(labels)


def normalize_message(message: TableDeltaMessage, *, previous: TableSnapshot | None = None) -> TableSnapshot:
    hero_cards = normalize_cards(message.hero_cards)
    board_cards = normalize_cards(message.board_cards)
    pot = normalize_money(message.pot_raw, message.pot_parsed)
    hero_stack = normalize_money(message.hero_stack_raw, message.hero_stack_parsed)

    slot_texts = (message.slot_left_raw, message.slot_centre_raw, message.slot_right_raw)
    legal_actions = legal_actions_from_slots(slot_texts, explicit=message.legal_actions)
    legal_actions_raw = tuple(text for text in slot_texts if text.strip())

    call_raw, call_parsed = amount_to_call_from_slots(slot_texts)
    if message.amount_to_call_raw or message.amount_to_call_parsed is not None:
        amount_to_call = normalize_money(message.amount_to_call_raw, message.amount_to_call_parsed)
    elif call_raw is not None:
        amount_to_call = normalize_money(call_raw, call_parsed)
    else:
        amount_to_call = normalize_money(None, None)

    street = _street_from_board(board_cards, message.street_hint)
    hand_id = previous.hand_id if previous is not None else 0
    generation = (previous.generation if previous is not None else 0) + 1

    if previous is not None and hero_cards and hero_cards != previous.hero_cards:
        hand_id += 1

    post_hand_ui = message.post_hand_ui or bool(message.post_hand_labels)
    hero_turn = message.hero_turn and not post_hand_ui

    snapshot = TableSnapshot(
        hand_id=hand_id,
        street=street,
        hero_cards=hero_cards,
        board_cards=board_cards,
        pot=pot,
        hero_stack=hero_stack,
        amount_to_call=amount_to_call,
        slot_left_raw=message.slot_left_raw,
        slot_centre_raw=message.slot_centre_raw,
        slot_right_raw=message.slot_right_raw,
        legal_actions_raw=legal_actions_raw,
        legal_actions_normalized=legal_actions,
        hero_turn=hero_turn,
        post_hand_ui=post_hand_ui,
        post_hand_labels=message.post_hand_labels,
        generation=generation,
        seq=message.seq,
        extract_sources=message.extract_sources,
    )
    return _apply_confidence(snapshot)


def _normalize_card(raw: str) -> str | None:
    cleaned = raw.strip().upper().replace(" ", "")
    if cleaned.startswith("10") and len(cleaned) >= 3:
        cleaned = f"T{cleaned[-1]}"
    if not _CARD_RE.match(cleaned if len(cleaned) == 2 else ""):
        if len(cleaned) == 2:
            rank, suit = cleaned[0], cleaned[1].lower()
            if rank in "23456789TJQKA" and suit in "cdhs":
                return f"{rank}{suit}"
        return None
    rank = cleaned[0] if cleaned[0] != "1" else "T"
    return f"{rank}{cleaned[-1].lower()}"


def _parse_money_text(raw: str) -> float | None:
    text = raw.strip().replace(",", "").replace("$", "").upper()
    match = re.search(r"(\d+(?:\.\d+)?)([KM])?", text)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2)
    if suffix == "K":
        value *= 1_000
    elif suffix == "M":
        value *= 1_000_000
    return value


def _labels_from_slot_text(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    labels: list[str] = []
    for label in ("fold", "check", "call", "raise", "bet"):
        if re.search(rf"\b{label}\b", lowered):
            labels.append(label)
    return tuple(labels)


def _street_from_board(board_cards: tuple[str, ...], street_hint: str | None) -> Street:
    if street_hint:
        try:
            return Street(street_hint.lower())
        except ValueError:
            pass
    if len(board_cards) >= 5:
        return Street.RIVER
    if len(board_cards) == 4:
        return Street.TURN
    if len(board_cards) == 3:
        return Street.FLOP
    if board_cards:
        return Street.UNKNOWN
    return Street.PREFLOP


def _apply_confidence(snapshot: TableSnapshot) -> TableSnapshot:
    from dataclasses import replace

    if snapshot.post_hand_ui:
        return replace(
            snapshot,
            state_confidence=StateConfidence.HIGH,
            block_reason="post_hand",
        )
    if len(snapshot.hero_cards) == 2 and snapshot.pot.parsed is not None:
        return replace(snapshot, state_confidence=StateConfidence.HIGH)
    notes: list[str] = []
    if len(snapshot.hero_cards) != 2:
        notes.append("hero_cards_incomplete")
    if snapshot.pot.parsed is None:
        notes.append("pot_unreadable")
    block_reason = snapshot.block_reason or (notes[0] if notes else None)
    return replace(
        snapshot,
        state_confidence=StateConfidence.LOW,
        block_reason=block_reason,
    )
