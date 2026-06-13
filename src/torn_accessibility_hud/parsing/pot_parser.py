"""Prefix-based pot OCR parsing for Torn's ``POT: $amount`` display."""

from __future__ import annotations

import re
from dataclasses import dataclass

_POT_ANCHOR_RE = re.compile(r"P[\s.\-]*O[\s.\-]*T", re.IGNORECASE)
_POT_ANCHOR_VARIANTS = ("POT", "P0T", "POT.", "P O T")
_CURRENCY_PREFIX_CHARS = frozenset("$£€5")
_PUNCT_AFTER_POT = frozenset(" \t:-.")


@dataclass(frozen=True)
class PotParseResult:
    normalized: float | None
    status: str
    candidate: str | None = None
    pot_crop_text: str = ""
    pot_anchor_index: int | None = None
    pot_digits_start: int | None = None

    @property
    def raw(self) -> str:
        return self.pot_crop_text


def parse_pot_text(raw: str) -> tuple[float | None, str]:
    """Parse a Torn pot OCR string; returns ``(amount, status)``."""

    result = parse_pot_text_detailed(raw)
    return result.normalized, result.status


def parse_pot_region_text(raw: str) -> PotParseResult:
    """Parse OCR from the dedicated pot crop (must contain a POT anchor)."""

    return parse_pot_text_detailed(raw)


def parse_pot_text_detailed(raw: str) -> PotParseResult:
    if not raw or not raw.strip():
        return PotParseResult(None, "empty", None, raw)

    anchor_index = _find_pot_anchor_index(raw)
    if anchor_index is None:
        return PotParseResult(None, "no_pot_marker", None, raw, None, None)

    cursor = anchor_index + 3
    while cursor < len(raw) and raw[cursor] in _PUNCT_AFTER_POT:
        cursor += 1

    digits_start = _skip_optional_currency_prefix(raw, cursor)
    candidate = _extract_digit_amount(raw, digits_start)
    if candidate is None:
        return PotParseResult(
            None,
            "no_money_token",
            None,
            raw,
            anchor_index,
            digits_start,
        )

    normalized = _digits_to_amount(candidate)
    if normalized is None:
        return PotParseResult(
            None,
            "invalid_token",
            candidate,
            raw,
            anchor_index,
            digits_start,
        )

    return PotParseResult(
        normalized,
        "ok",
        candidate,
        raw,
        anchor_index,
        digits_start,
    )


def _find_pot_anchor_index(text: str) -> int | None:
    match = _POT_ANCHOR_RE.search(text)
    if match is not None:
        return match.start()

    upper = text.upper()
    for variant in _POT_ANCHOR_VARIANTS:
        compact = variant.replace(" ", "")
        index = upper.find(compact)
        if index >= 0:
            return index
    return None


def _skip_optional_currency_prefix(text: str, start: int) -> int:
    """Skip one currency/junk character immediately before the amount digits."""

    if start >= len(text):
        return start

    char = text[start]
    if char in "$£€":
        return start + 1

    if char == "5" and _should_skip_misread_dollar_prefix(text, start):
        return start + 1

    if not char.isdigit() and start + 1 < len(text) and text[start + 1].isdigit():
        return start + 1

    return start


def _should_skip_misread_dollar_prefix(text: str, start: int) -> bool:
    """Skip a leading 5 only when it likely represents a misread dollar sign."""

    digit_run = _peek_digit_comma_run(text, start)
    digits_only = re.sub(r"[^\d]", "", digit_run)
    return len(digits_only) >= 4


def _peek_digit_comma_run(text: str, start: int) -> str:
    candidate, _end = _extract_digit_amount_with_end(text, start)
    return candidate or ""


def _extract_digit_amount(text: str, start: int) -> str | None:
    candidate, _end = _extract_digit_amount_with_end(text, start)
    return candidate


def _extract_digit_amount_with_end(text: str, start: int) -> tuple[str | None, int]:
    if start >= len(text) or not text[start].isdigit():
        return None, start

    chars: list[str] = []
    cursor = start

    while cursor < len(text) and text[cursor].isdigit():
        chars.append(text[cursor])
        cursor += 1

    while cursor < len(text) and text[cursor] == ",":
        group = text[cursor + 1 : cursor + 4]
        if len(group) != 3 or not group.isdigit():
            break
        chars.append(",")
        chars.extend(group)
        cursor += 4

    candidate = "".join(chars)
    if not candidate:
        return None, cursor
    return candidate, cursor


def _digits_to_amount(candidate: str) -> float | None:
    compact = candidate.replace(",", "")
    if not compact.isdigit():
        return None
    value = float(compact)
    if value <= 0:
        return None
    return value
