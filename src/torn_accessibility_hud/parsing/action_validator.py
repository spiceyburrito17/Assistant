"""Validate legal actions and amount-to-call before strategy runs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import RecommendedAction
from .amounts import isolate_call_slot_text, parse_amount_to_call_from_action_text, raise_to_pattern_present
from .legal_actions import LEGAL_ACTION_LABELS, legal_action_to_recommended

STRICT_LABELS: frozenset[str] = frozenset({"fold", "check", "call", "bet", "raise"})


@dataclass(frozen=True)
class AmountToCallRead:
    raw_text: str | None
    parsed: float | None
    status: str


@dataclass(frozen=True)
class ValidatedActionInputs:
    legal_actions: tuple[RecommendedAction, ...]
    normalized_labels: tuple[str, ...]
    raw_entries: tuple[str, ...]
    actions_ambiguous: bool
    amount_to_call: AmountToCallRead
    to_call: float | None
    block_reason: str | None


def validate_action_inputs(
    *,
    normalized_labels: tuple[str, ...],
    raw_entries: tuple[str, ...],
    actions_ambiguous: bool,
    call_slot_raw: str | None = None,
    raise_slot_raw: str | None = None,
    action_regions_scanned: bool,
    call_button_raw: str | None = None,
    raise_button_raw: str | None = None,
) -> ValidatedActionInputs:
    """Apply check/call, bet/raise, and to-call rules to action-bar slot OCR."""

    effective_call_raw = call_slot_raw if call_slot_raw is not None else call_button_raw
    effective_raise_raw = raise_slot_raw if raise_slot_raw is not None else raise_button_raw
    labels = _dedupe_labels(label for label in normalized_labels if label in STRICT_LABELS)
    amount_read = _read_amount_to_call(effective_call_raw)
    to_call = _resolve_to_call(amount_read)

    if actions_ambiguous:
        return ValidatedActionInputs(
            legal_actions=(),
            normalized_labels=labels,
            raw_entries=raw_entries,
            actions_ambiguous=True,
            amount_to_call=amount_read,
            to_call=to_call,
            block_reason="actions_ambiguous",
        )

    labels = _apply_check_call_rules(labels, amount_read, to_call)
    labels = _apply_bet_raise_rules(labels, to_call, raise_slot_raw=effective_raise_raw)
    legal_actions = _to_recommended(labels)

    resolved_to_call = to_call
    if resolved_to_call is None and RecommendedAction.CHECK in legal_actions:
        resolved_to_call = 0.0

    block_reason = _derive_action_block_reason(
        legal_actions=legal_actions,
        amount_read=amount_read,
        action_regions_scanned=action_regions_scanned,
    )

    return ValidatedActionInputs(
        legal_actions=legal_actions,
        normalized_labels=labels,
        raw_entries=raw_entries,
        actions_ambiguous=False,
        amount_to_call=amount_read,
        to_call=resolved_to_call,
        block_reason=block_reason,
    )


def _dedupe_labels(labels: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    merged: list[str] = []
    seen: set[str] = set()
    for label in labels:
        if label not in seen:
            merged.append(label)
            seen.add(label)
    return tuple(merged)


def _read_amount_to_call(call_button_raw: str | None) -> AmountToCallRead:
    if not call_button_raw or not call_button_raw.strip():
        return AmountToCallRead(None, None, "empty")
    isolated = isolate_call_slot_text(call_button_raw)
    parsed, status = parse_amount_to_call_from_action_text(call_button_raw)
    return AmountToCallRead(isolated or call_button_raw.strip(), parsed, status)


def _resolve_to_call(amount_read: AmountToCallRead) -> float | None:
    if amount_read.status == "ok" and amount_read.parsed is not None:
        return max(0.0, amount_read.parsed)
    if amount_read.status == "zero":
        return 0.0
    return None


def _apply_check_call_rules(
    labels: tuple[str, ...],
    amount_read: AmountToCallRead,
    to_call: float | None,
) -> tuple[str, ...]:
    label_set = set(labels)
    if "check" not in label_set and "call" not in label_set:
        return labels

    effective_to_call = to_call
    if effective_to_call is None and amount_read.status == "empty":
        effective_to_call = 0.0

    if "check" in label_set and "call" in label_set:
        if effective_to_call is not None and effective_to_call > 0:
            label_set.discard("check")
        else:
            label_set.discard("call")

    if "check" in label_set and "call" in label_set:
        label_set.discard("call")

    return _ordered_labels(label_set)


def _ordered_labels(label_set: set[str]) -> tuple[str, ...]:
    return tuple(label for label in LEGAL_ACTION_LABELS if label in label_set)


def _apply_bet_raise_rules(
    labels: tuple[str, ...],
    to_call: float | None,
    *,
    raise_slot_raw: str | None = None,
    raise_button_raw: str | None = None,
) -> tuple[str, ...]:
    effective_raise_raw = raise_slot_raw if raise_slot_raw is not None else raise_button_raw
    label_set = set(labels)
    facing_bet = to_call is not None and to_call > 0
    raise_wording = raise_to_pattern_present(effective_raise_raw) or (
        effective_raise_raw is not None
        and re.search(r"\braise\b", effective_raise_raw, re.IGNORECASE) is not None
    )

    if raise_wording:
        label_set.discard("bet")
        if "raise" not in label_set:
            label_set.add("raise")
        return _ordered_labels(label_set)

    if facing_bet:
        label_set.discard("bet")
        if "raise" not in label_set and "bet" in labels:
            label_set.add("raise")
        return _ordered_labels(label_set)

    if "raise" in label_set and effective_raise_raw:
        if re.search(r"\bbet\b", effective_raise_raw, re.IGNORECASE) and not re.search(
            r"\braise\b", effective_raise_raw, re.IGNORECASE
        ):
            label_set.discard("raise")
            label_set.add("bet")

    return _ordered_labels(label_set)


def _to_recommended(labels: tuple[str, ...]) -> tuple[RecommendedAction, ...]:
    merged: list[RecommendedAction] = []
    seen: set[RecommendedAction] = set()
    for label in labels:
        recommended = legal_action_to_recommended(label)
        if recommended in seen:
            continue
        merged.append(recommended)
        seen.add(recommended)
    return tuple(merged)


def _derive_action_block_reason(
    *,
    legal_actions: tuple[RecommendedAction, ...],
    amount_read: AmountToCallRead,
    action_regions_scanned: bool,
) -> str | None:
    if not legal_actions:
        return "legal_actions_missing"
    if RecommendedAction.CALL not in legal_actions:
        return None
    if not action_regions_scanned:
        return None
    if amount_read.status in {"ok", "zero"}:
        if amount_read.parsed is None or amount_read.parsed <= 0:
            if RecommendedAction.CHECK in legal_actions:
                return None
            return "amount_to_call_unreadable"
        return None
    if amount_read.status == "no_call_marker":
        return "amount_to_call_unreadable"
    return "amount_to_call_unreadable"
