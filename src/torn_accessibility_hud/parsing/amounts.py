"""Shared chip amount parsing for log and region OCR."""

from __future__ import annotations

import re

_AMOUNT_RE = re.compile(r"(?<![a-z])(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_TO_CALL_BUTTON_RE = re.compile(
    r"\bcall\b[^0-9$£€]*(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_CHECK_BUTTON_RE = re.compile(r"\bcheck\b", re.IGNORECASE)


def parse_chip_amount(raw: str | None, *, max_reasonable: float = 10_000_000.0) -> float | None:
    if not raw:
        return None
    match = _AMOUNT_RE.search(raw)
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if value < 0 or value > max_reasonable:
        return None
    return value


def parse_to_call_from_button_text(text: str, *, max_reasonable: float = 10_000_000.0) -> float | None:
    parsed, status = parse_amount_to_call_from_action_text(text, max_reasonable=max_reasonable)
    if status == "ok" and parsed is not None:
        return parsed
    return None


def parse_amount_to_call_from_action_text(
    text: str,
    *,
    max_reasonable: float = 10_000_000.0,
) -> tuple[float | None, str]:
    """Parse to-call only from hero action button OCR (Call slot)."""

    stripped = text.strip()
    if not stripped:
        return None, "empty"

    if _CHECK_BUTTON_RE.search(stripped) and _TO_CALL_BUTTON_RE.search(stripped) is None:
        return 0.0, "zero"

    match = _TO_CALL_BUTTON_RE.search(stripped)
    if match is None:
        if _CHECK_BUTTON_RE.search(stripped):
            return 0.0, "zero"
        return None, "no_call_marker"

    value = parse_chip_amount(match.group(1), max_reasonable=max_reasonable)
    if value is None:
        return None, "invalid_amount"
    if value <= 0:
        return 0.0, "zero"
    return value, "ok"
