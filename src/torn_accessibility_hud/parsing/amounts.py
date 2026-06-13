"""Shared chip amount parsing for log and region OCR."""

from __future__ import annotations

import re

_AMOUNT_RE = re.compile(r"(?<![a-z])(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_TO_CALL_BUTTON_RE = re.compile(r"\bcall\b[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)


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
    match = _TO_CALL_BUTTON_RE.search(text.strip())
    if match is None:
        return None
    return parse_chip_amount(match.group(1), max_reasonable=max_reasonable)
