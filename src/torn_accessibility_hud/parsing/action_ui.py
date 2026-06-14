"""Detect post-hand UI in action-bar OCR text."""

from __future__ import annotations

import re

POST_HAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bshow\s+cards\b", re.IGNORECASE),
    re.compile(r"\bsit\s+out\b", re.IGNORECASE),
    re.compile(r"\bleave\b", re.IGNORECASE),
)


def is_post_hand_ui(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    return any(pattern.search(text) for pattern in POST_HAND_PATTERNS)


def detect_post_hand_ui(*texts: str | None) -> bool:
    return any(is_post_hand_ui(text) for text in texts)
