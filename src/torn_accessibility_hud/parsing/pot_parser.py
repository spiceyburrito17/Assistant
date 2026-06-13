"""Prefix-based pot OCR parsing for Torn's ``POT: $amount`` display."""

from __future__ import annotations

import re
from dataclasses import dataclass

_POT_TARGET = "POT"
_PUNCT_AFTER_POT = frozenset(" \t:-.;")
_MIN_WEAK_DIGITS = 3


@dataclass(frozen=True)
class PotAnchorMatch:
    index: int
    matched: str
    confidence: float
    length: int


@dataclass(frozen=True)
class PotParseResult:
    normalized: float | None
    status: str
    candidate: str | None = None
    pot_crop_text: str = ""
    pot_anchor_index: int | None = None
    pot_anchor_match: str | None = None
    pot_anchor_confidence: float | None = None
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

    anchor = _find_pot_anchor(raw)
    if anchor is None:
        return PotParseResult(None, "no_pot_marker", None, raw)

    cursor = anchor.index + anchor.length
    while cursor < len(raw) and raw[cursor] in _PUNCT_AFTER_POT:
        cursor += 1

    digits_start = _skip_optional_currency_prefix(raw, cursor)
    candidate = _extract_digit_amount(raw, digits_start)
    if candidate is None:
        return _result(
            None,
            "no_money_token",
            candidate,
            raw,
            anchor,
            digits_start,
        )

    weak_reason = _weak_read_reason(anchor.confidence, candidate)
    if weak_reason is not None:
        return _result(None, weak_reason, candidate, raw, anchor, digits_start)

    normalized = _digits_to_amount(candidate)
    if normalized is None:
        return _result(None, "invalid_token", candidate, raw, anchor, digits_start)

    return _result(normalized, "ok", candidate, raw, anchor, digits_start)


def _result(
    normalized: float | None,
    status: str,
    candidate: str | None,
    raw: str,
    anchor: PotAnchorMatch,
    digits_start: int | None,
) -> PotParseResult:
    return PotParseResult(
        normalized=normalized,
        status=status,
        candidate=candidate,
        pot_crop_text=raw,
        pot_anchor_index=anchor.index,
        pot_anchor_match=anchor.matched,
        pot_anchor_confidence=anchor.confidence,
        pot_digits_start=digits_start,
    )


def _find_pot_anchor(text: str) -> PotAnchorMatch | None:
    upper = text.upper()
    candidates: list[PotAnchorMatch] = []

    for index in range(max(len(upper) - 2, 0)):
        window = upper[index : index + 3]
        if not window.isalnum():
            continue
        distance = _edit_distance(window, _POT_TARGET)
        if distance <= 1:
            candidates.append(
                PotAnchorMatch(
                    index=index,
                    matched=text[index : index + 3],
                    confidence=_anchor_confidence(distance),
                    length=3,
                )
            )

    for match in re.finditer(r"P[\s.\-;]*[O0Q][\s.\-;]*[TI7L1]", upper):
        collapsed = re.sub(r"[\s.\-;]", "", match.group())
        if len(collapsed) != 3:
            continue
        distance = _edit_distance(collapsed, _POT_TARGET)
        if distance <= 1:
            candidates.append(
                PotAnchorMatch(
                    index=match.start(),
                    matched=text[match.start() : match.end()],
                    confidence=_anchor_confidence(distance),
                    length=match.end() - match.start(),
                )
            )

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda item: (item.confidence, -item.index),
    )


def _anchor_confidence(distance: int) -> float:
    if distance <= 0:
        return 1.0
    if distance == 1:
        return 0.75
    return 0.5


def _edit_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    return sum(a != b for a, b in zip(left, right, strict=True))


def _weak_read_reason(anchor_confidence: float, candidate: str) -> str | None:
    digits = re.sub(r"[^\d]", "", candidate)
    if anchor_confidence < 1.0 and len(digits) < _MIN_WEAK_DIGITS:
        return "weak_anchor_and_digits"
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
