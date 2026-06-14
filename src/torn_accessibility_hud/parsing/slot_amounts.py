"""OCR-tolerant normalisation for dollar amounts in action-slot text."""

from __future__ import annotations

import re

from .amounts import parse_amount_to_call_from_action_text, parse_chip_amount, raise_to_pattern_present

_OCR_AMOUNT_CHAR_MAP = str.maketrans(
    {
        "z": "2",
        "Z": "2",
        "o": "0",
        "O": "0",
        "i": "1",
        "I": "1",
        "l": "1",
        "L": "1",
        "A": "4",
        "B": "8",
        "g": "9",
        "q": "9",
    }
)

_MONEY_TOKEN_PATTERN = r"[A-Za-z$£€][A-Za-z0-9$£€.,]*"
_MONEY_AFTER_CALL = re.compile(rf"(\bcall\b\s+)({_MONEY_TOKEN_PATTERN})", re.IGNORECASE)
_MONEY_AFTER_RAISE_TO = re.compile(rf"(\braise\s+to\b\s+)({_MONEY_TOKEN_PATTERN})", re.IGNORECASE)


def normalize_slot_money_token(token: str) -> str:
    """Normalise one OCR money token (e.g. ``Szo`` → ``$20``)."""

    cleaned = token.strip()
    if not cleaned:
        return cleaned
    if cleaned[0] in "Ss":
        cleaned = "$" + cleaned[1:]
    return cleaned.translate(_OCR_AMOUNT_CHAR_MAP)


def normalize_slot_action_text_for_amounts(text: str) -> str:
    """Rewrite only the numeric token after ``CALL`` or ``RAISE TO``."""

    def _replace(match: re.Match[str]) -> str:
        token = match.group(2)
        if token.strip().lower() == "any":
            return match.group(0)
        return match.group(1) + normalize_slot_money_token(token)

    normalized = _MONEY_AFTER_RAISE_TO.sub(_replace, text)
    return _MONEY_AFTER_CALL.sub(_replace, normalized)


def parse_raise_to_amount_from_action_text(
    text: str,
    *,
    max_reasonable: float = 10_000_000.0,
) -> float | None:
    normalized = normalize_slot_action_text_for_amounts(text)
    if not raise_to_pattern_present(normalized):
        return None
    match = re.search(
        rf"\braise\s+to\b\s+(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*([KkMm])?",
        normalized,
        re.IGNORECASE,
    )
    if match is None:
        token_match = _MONEY_AFTER_RAISE_TO.search(normalized)
        if token_match is None:
            return None
        return parse_chip_amount(normalize_slot_money_token(token_match.group(2)), max_reasonable=max_reasonable)
    amount_text = match.group(1)
    if match.group(2):
        amount_text = f"{amount_text}{match.group(2)}"
    return parse_chip_amount(amount_text, max_reasonable=max_reasonable)


def parse_amount_to_call_from_slot_text(
    text: str,
    *,
    max_reasonable: float = 10_000_000.0,
) -> tuple[float | None, str]:
    return parse_amount_to_call_from_action_text(
        normalize_slot_action_text_for_amounts(text),
        max_reasonable=max_reasonable,
    )
