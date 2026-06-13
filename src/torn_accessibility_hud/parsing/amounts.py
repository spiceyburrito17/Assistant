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


def parse_pot_amount_from_text(text: str, *, max_reasonable: float = 10_000_000.0) -> float | None:
    """Parse a pot/chip amount from noisy OCR text."""

    cleaned = text.strip()
    if not cleaned:
        return None
    amount = parse_chip_amount(cleaned, max_reasonable=max_reasonable)
    if amount is None:
        digits_only = re.sub(r"[^\d.,]", "", cleaned)
        amount = parse_chip_amount(digits_only, max_reasonable=max_reasonable)
    if amount is None:
        return None
    digits = re.sub(r"\D", "", cleaned)
    has_currency_marker = any(marker in cleaned for marker in "$£€")
    if has_currency_marker or len(digits) != 3:
        return amount
    corrected: str | None = None
    if len(digits) == 3 and digits[1] == "4":
        corrected = f"{digits[0]}{digits[2]}"
    elif len(digits) == 3 and digits[0] == "5" and digits[1] == digits[2]:
        corrected = digits[1:]
    if corrected is None:
        return amount
    return parse_chip_amount(corrected, max_reasonable=max_reasonable) or amount


def parse_to_call_from_button_text(text: str, *, max_reasonable: float = 10_000_000.0) -> float | None:
    match = _TO_CALL_BUTTON_RE.search(text.strip())
    if match is None:
        return None
    return parse_chip_amount(match.group(1), max_reasonable=max_reasonable)
