"""Pot-specific OCR parsing for Torn's ``POT: $1,234`` display format."""

from __future__ import annotations

import re
from dataclasses import dataclass

# First money token only — do not scan the rest of the line for extras.
_POT_MONEY_TOKEN_RE = re.compile(
    r"^\s*(?P<token>\$?\s*(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,7}))"
)


@dataclass(frozen=True)
class PotParseResult:
    normalized: float | None
    status: str
    candidate: str | None = None
    raw: str = ""


def parse_pot_text(raw: str) -> tuple[float | None, str]:
    """Parse a Torn pot OCR string; returns ``(amount, status)``."""

    result = parse_pot_text_detailed(raw)
    return result.normalized, result.status


def parse_pot_region_text(raw: str) -> PotParseResult:
    """Parse OCR from the dedicated pot crop (with or without a POT label)."""

    detailed = parse_pot_text_detailed(raw)
    if detailed.normalized is not None:
        return detailed
    if detailed.status not in {"no_pot_marker", "no_money_token"}:
        return detailed

    trimmed = raw.strip()
    token_match = _POT_MONEY_TOKEN_RE.match(trimmed)
    if token_match is None:
        return detailed

    candidate = token_match.group("token").strip()
    normalized, status = _normalize_pot_candidate(candidate)
    return PotParseResult(normalized, status, candidate, raw)


def parse_pot_text_detailed(raw: str) -> PotParseResult:
    if not raw or not raw.strip():
        return PotParseResult(None, "empty", None, raw)

    upper = raw.upper()
    pot_index = upper.find("POT")
    if pot_index < 0:
        return PotParseResult(None, "no_pot_marker", None, raw)

    after_pot = raw[pot_index + 3 :]
    after_pot = re.sub(r"^[\s:\-]+", "", after_pot)
    token_match = _POT_MONEY_TOKEN_RE.match(after_pot)
    if token_match is None:
        return PotParseResult(None, "no_money_token", None, raw)

    candidate = token_match.group("token").strip()
    normalized, status = _normalize_pot_candidate(candidate)
    return PotParseResult(normalized, status, candidate, raw)


def _normalize_pot_candidate(candidate: str) -> tuple[float | None, str]:
    has_dollar = "$" in candidate
    digits = re.sub(r"[^\d]", "", candidate)
    if not digits:
        return None, "invalid_token"

    corrected, note = _apply_pot_digit_corrections(digits, has_dollar=has_dollar)
    try:
        value = float(corrected)
    except ValueError:
        return None, "invalid_token"
    if value <= 0:
        return None, "invalid_token"
    return value, note


def _apply_pot_digit_corrections(digits: str, *, has_dollar: bool) -> tuple[str, str]:
    if has_dollar:
        return digits, "ok"

    if len(digits) >= 4 and digits[0] == "5":
        without_leading = digits[1:]
        if without_leading and int(digits) >= int(without_leading) * 8:
            return without_leading, "leading_5_as_dollar"

    if len(digits) == 3 and digits[1] == "4" and digits[0] == digits[2]:
        return f"{digits[0]}{digits[2]}", "middle_4_as_dollar"

    if len(digits) == 3 and digits[0] == "5" and digits[1] == digits[2]:
        return digits[1:], "leading_5_duplicate"

    return digits, "ok"
