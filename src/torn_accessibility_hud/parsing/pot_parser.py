"""Prefix-based pot OCR parsing for Torn's ``POT: $amount`` display."""

from __future__ import annotations

import re
from dataclasses import dataclass

_POT_TARGET = "POT"
_PUNCT_AFTER_POT = frozenset(" \t:-.;")
_MIN_WEAK_DIGITS = 3
_MISREAD_DOLLAR_DIGITS = frozenset("568")
_CURRENCY_CHARS = frozenset("$£€")
# Per-position OCR confusions when the pot allowlist excludes letters (POT read as 816).
_POT_OCR_EQUIV: tuple[frozenset[str], ...] = (
    frozenset("P89"),
    frozenset("O0Q8D61"),
    frozenset("T7I1L6F"),
)
_OCR_DIGIT_ANCHOR_CONFIDENCE = 0.55


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
    cursor = _skip_pot_label_suffix(raw, cursor)

    digits_start, candidate = _resolve_amount_token(raw, cursor)
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


def _skip_pot_label_suffix(text: str, start: int) -> int:
    """Skip ``POT: $`` label tail: punctuation, whitespace, then one currency slot."""

    cursor = start
    while cursor < len(text) and text[cursor] in _PUNCT_AFTER_POT:
        cursor += 1
    return _skip_optional_currency_prefix(text, cursor)


def _resolve_amount_token(text: str, cursor: int) -> tuple[int, str | None]:
    """Resolve the first money token, retrying without a skipped currency char."""

    digits_start = _skip_optional_currency_prefix(text, cursor)
    candidate = _extract_digit_amount(text, digits_start)
    if candidate is not None and _digits_to_amount(candidate) is not None:
        return digits_start, candidate

    if digits_start != cursor:
        candidate = _extract_digit_amount(text, cursor)
        if candidate is not None:
            return cursor, candidate

    return digits_start, candidate


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
            continue
        if _ocr_pot_window_matches(window):
            candidates.append(
                PotAnchorMatch(
                    index=index,
                    matched=text[index : index + 3],
                    confidence=_ocr_digit_anchor_confidence(window),
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


def _ocr_pot_window_matches(window: str) -> bool:
    if len(window) != 3:
        return False
    for char, equiv in zip(window.upper(), _POT_OCR_EQUIV, strict=True):
        if char not in equiv:
            return False
    return True


def _ocr_digit_anchor_confidence(window: str) -> float:
    if window.upper() == _POT_TARGET:
        return 1.0
    if window.isdigit():
        return _OCR_DIGIT_ANCHOR_CONFIDENCE
    return 0.65


def _weak_read_reason(anchor_confidence: float, candidate: str) -> str | None:
    digits = re.sub(r"[^\d]", "", candidate)
    if anchor_confidence < 1.0 and len(digits) < _MIN_WEAK_DIGITS:
        return "weak_anchor_and_digits"
    return None


def _skip_optional_currency_prefix(text: str, start: int) -> int:
    """Skip one ``$`` slot or common OCR misread of it before amount digits."""

    if start >= len(text):
        return start

    char = text[start]
    if char in _CURRENCY_CHARS:
        return start + 1

    if char in "Ss" and start + 1 < len(text) and text[start + 1].isdigit():
        return start + 1

    if char in _MISREAD_DOLLAR_DIGITS:
        full_candidate = _extract_digit_amount(text, start)
        if full_candidate is not None:
            skipped_candidate = _extract_digit_amount(text, start + 1)
            if skipped_candidate and _should_skip_misread_dollar_digit(full_candidate, skipped_candidate):
                return start + 1

    if not char.isdigit() and start + 1 < len(text) and text[start + 1].isdigit():
        return start + 1

    return start


def _should_skip_misread_dollar_digit(full: str, skipped: str) -> bool:
    """Treat a leading ``5``/``6``/``8`` as a misread dollar sign before the real amount."""

    full_digits = re.sub(r"[^\d]", "", full)
    skipped_digits = re.sub(r"[^\d]", "", skipped)
    if not full_digits or full_digits[0] not in _MISREAD_DOLLAR_DIGITS or not skipped_digits:
        return False
    try:
        full_val = float(full_digits)
        skipped_val = float(skipped_digits)
    except ValueError:
        return False
    if skipped_val <= 0:
        return False

    if "," in full:
        return _should_skip_misread_dollar_digit_with_comma(
            full,
            skipped,
            full_val,
            skipped_val,
        )

    return _should_skip_misread_dollar_digit_without_comma(
        full_digits,
        skipped_digits,
        full_val,
        skipped_val,
    )


def _should_skip_misread_dollar_digit_without_comma(
    full_digits: str,
    skipped_digits: str,
    full_val: float,
    skipped_val: float,
) -> bool:
    """Heuristic when OCR dropped commas (e.g. ``8120`` for ``$120``)."""

    leading = full_digits[0]
    digit_len = len(full_digits)

    # ``POT: $120`` often OCRs as ``8120`` — four digits, no comma, leading ``8``.
    if digit_len == 4 and leading == "8":
        return True

    if digit_len == 3 and len(skipped_digits) >= 2:
        return full_val / skipped_val < 8.0

    # ``5660`` → ``660`` and ``6190`` → ``190``, but not ``5120`` → ``120`` for ``$5,120``.
    if digit_len == 4 and leading in "56":
        return full_val / skipped_val < 40.0

    return False


def _should_skip_misread_dollar_digit_with_comma(
    full: str,
    skipped: str,
    full_val: float,
    skipped_val: float,
) -> bool:
    """Heuristic when commas are present — Torn uses ``X,XXX`` / ``XX,XXX`` grouping."""

    before_comma = full.split(",", 1)[0]
    if before_comma.isdigit() and len(before_comma) == 1:
        # ``8,120`` / ``5,120``: single digit before comma is a real thousands digit.
        return False

    if "," not in skipped:
        return False

    skipped_before_comma = skipped.split(",", 1)[0]
    if skipped_before_comma.isdigit() and len(skipped_before_comma) == 1:
        # ``51,145`` → ``1,145``: misread ``$`` prepended to a comma-formatted amount.
        return full_val / skipped_val < 50.0

    return False


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
