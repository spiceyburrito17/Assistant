"""Per-button-slot OCR text isolation and amount-to-call parsing."""

from __future__ import annotations

import re

_AMOUNT_RE = re.compile(r"(?<![a-z])(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_CALL_AMOUNT_RE = re.compile(
    r"\bcall\b[^0-9$£€]*(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_CHECK_RE = re.compile(r"\bcheck\b", re.IGNORECASE)
_RAISE_TO_RE = re.compile(r"\braise\s+to\b", re.IGNORECASE)
_CALL_OR_CHECK_START_RE = re.compile(r"\b(check|call)\b", re.IGNORECASE)
_RAISE_OR_BET_START_RE = re.compile(r"\b(raise\s+to|raise|bet)\b", re.IGNORECASE)
_FOLD_START_RE = re.compile(r"\bfold\b", re.IGNORECASE)


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


def isolate_call_slot_text(text: str) -> str:
    """Drop leading ``RAISE TO ...`` noise; keep only the check/call tail."""

    stripped = text.strip()
    if not stripped:
        return stripped
    match = _CALL_OR_CHECK_START_RE.search(stripped)
    if match is None:
        return stripped
    return stripped[match.start() :].strip()


def isolate_raise_slot_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    match = _RAISE_OR_BET_START_RE.search(stripped)
    if match is None:
        return stripped
    return stripped[match.start() :].strip()


def isolate_fold_slot_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    match = _FOLD_START_RE.search(stripped)
    if match is None:
        return stripped
    return stripped[match.start() :].strip()


def isolate_button_slot_text(region_name: str, text: str) -> str:
    if region_name == "call_button_region":
        return isolate_call_slot_text(text)
    if region_name == "raise_button_region":
        return isolate_raise_slot_text(text)
    if region_name == "fold_button_region":
        return isolate_fold_slot_text(text)
    return text.strip()


def raise_to_pattern_present(text: str | None) -> bool:
    if not text:
        return False
    return _RAISE_TO_RE.search(text) is not None


def parse_amount_to_call_from_action_text(
    text: str,
    *,
    max_reasonable: float = 10_000_000.0,
) -> tuple[float | None, str]:
    """Parse to-call only from the dedicated call/check button crop."""

    isolated = isolate_call_slot_text(text)
    stripped = isolated.strip()
    if not stripped:
        return None, "empty"

    if _CHECK_RE.search(stripped) and _CALL_AMOUNT_RE.search(stripped) is None:
        return 0.0, "zero"

    match = _CALL_AMOUNT_RE.search(stripped)
    if match is None:
        if _CHECK_RE.search(stripped):
            return 0.0, "zero"
        return None, "no_call_marker"

    value = parse_chip_amount(match.group(1), max_reasonable=max_reasonable)
    if value is None:
        return None, "invalid_amount"
    if value <= 0:
        return 0.0, "zero"
    return value, "ok"


def parse_to_call_from_button_text(text: str, *, max_reasonable: float = 10_000_000.0) -> float | None:
    parsed, status = parse_amount_to_call_from_action_text(text, max_reasonable=max_reasonable)
    if status == "ok" and parsed is not None:
        return parsed
    if status == "zero":
        return 0.0
    return None


def call_amount_present(text: str) -> bool:
    parsed, status = parse_amount_to_call_from_action_text(text)
    return status == "ok" and parsed is not None and parsed > 0


def button_texts_overlap(left: str, right: str) -> bool:
    left_norm = re.sub(r"\s+", " ", left.strip().lower())
    right_norm = re.sub(r"\s+", " ", right.strip().lower())
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    shorter, longer = sorted((left_norm, right_norm), key=len)
    if len(shorter) >= 8 and shorter in longer:
        return True
    return False
