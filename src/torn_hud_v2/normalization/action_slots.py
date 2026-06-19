"""Classify Torn action-bar slot text into normalized legal actions."""

from __future__ import annotations

import re

_ACTION_LABELS = frozenset({"fold", "check", "call", "raise", "bet"})

_CALL_ANY_RE = re.compile(r"\bcall\s+any\b", re.IGNORECASE)
_FOLD_RE = re.compile(r"\bfold\b", re.IGNORECASE)
_CHECK_RE = re.compile(r"\bcheck\b", re.IGNORECASE)
_CALL_RE = re.compile(r"\bcall\b", re.IGNORECASE)
_RAISE_RE = re.compile(r"\braise\b", re.IGNORECASE)
_BET_RE = re.compile(r"\bbet\b", re.IGNORECASE)
_POST_HAND_RE = re.compile(r"\b(show\s+cards|sit\s+out|leave)\b", re.IGNORECASE)


def classify_slot_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if _POST_HAND_RE.search(stripped):
        return None
    if _FOLD_RE.search(stripped):
        return "fold"
    if _CALL_ANY_RE.search(stripped):
        return "check"
    if _CHECK_RE.search(stripped):
        return "check"
    if _RAISE_RE.search(stripped):
        return "raise"
    if _BET_RE.search(stripped):
        return "bet"
    if _CALL_RE.search(stripped):
        return "call"
    return None


def legal_actions_from_slots(
    slot_texts: tuple[str, ...],
    *,
    explicit: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if explicit:
        return tuple(label for label in explicit if label in _ACTION_LABELS)

    labels: list[str] = []
    seen: set[str] = set()
    for text in slot_texts:
        label = classify_slot_text(text)
        if label is None or label in seen:
            continue
        labels.append(label)
        seen.add(label)
    return tuple(labels)


def amount_to_call_from_slots(slot_texts: tuple[str, ...]) -> tuple[str | None, float | None]:
    from .normalize import _parse_money_text

    for text in slot_texts:
        if not text or not _CALL_RE.search(text):
            continue
        if _CALL_ANY_RE.search(text):
            return text, 0.0
        parsed = _parse_money_text(text)
        if parsed is not None:
            return text, parsed
    return None, None
