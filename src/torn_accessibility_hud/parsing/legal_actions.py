"""Parse visible hero action buttons from OCR text."""

from __future__ import annotations

import re

from ..models import RecommendedAction

_BUTTON_WORDS: tuple[tuple[str, RecommendedAction], ...] = (
    ("all in", RecommendedAction.RAISE),
    ("all-in", RecommendedAction.RAISE),
    ("raise", RecommendedAction.RAISE),
    ("bet", RecommendedAction.RAISE),
    ("call", RecommendedAction.CALL),
    ("check", RecommendedAction.CHECK),
    ("fold", RecommendedAction.FOLD),
)
_BUTTON_LINE_RE = re.compile(
    r"^\s*(?:\[|\()?(?P<action>all[\s-]?in|raise|bet|call|check|fold)\b",
    re.IGNORECASE,
)


def parse_legal_actions_from_text(text: str) -> tuple[RecommendedAction, ...]:
    """Extract hero button labels from one OCR line."""

    lowered = text.strip().lower()
    if not lowered:
        return ()
    actions: list[RecommendedAction] = []
    seen: set[RecommendedAction] = set()
    for token, action in _BUTTON_WORDS:
        if token in lowered and action not in seen:
            actions.append(action)
            seen.add(action)
    if actions:
        return tuple(actions)
    match = _BUTTON_LINE_RE.match(lowered)
    if match is None:
        return ()
    compact = match.group("action").replace("-", " ")
    for token, action in _BUTTON_WORDS:
        if compact.startswith(token):
            return (action,)
    return ()


def parse_legal_actions_from_lines(lines: tuple[str, ...]) -> tuple[RecommendedAction, ...]:
    """Merge visible hero buttons detected across OCR lines."""

    merged: list[RecommendedAction] = []
    seen: set[RecommendedAction] = set()
    for line in lines:
        for action in parse_legal_actions_from_text(line):
            if action in seen:
                continue
            merged.append(action)
            seen.add(action)
    return tuple(merged)
