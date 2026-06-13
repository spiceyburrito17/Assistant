"""Sanity checks for trusted pot updates within a hand."""

from __future__ import annotations

MAX_REASONABLE_POT = 10_000_000.0
MAX_POT_JUMP_RATIO = 12.0
TABLE_REGION_CORRECTION_RATIO = 3.0


def validate_pot_update(
    candidate: float,
    *,
    previous: float | None,
    hand_reset: bool,
    from_table_region: bool = False,
) -> tuple[float | None, str | None]:
    """Accept or reject a parsed pot relative to the last trusted value."""

    if candidate <= 0 or candidate > MAX_REASONABLE_POT:
        return None, "absurd magnitude"

    if hand_reset or previous is None:
        return candidate, None

    if candidate < previous:
        if _allows_pot_decrease(previous, candidate, from_table_region=from_table_region):
            return candidate, None
        return None, "pot decreased within hand"

    if candidate > previous * MAX_POT_JUMP_RATIO:
        return None, f"pot jump too large ({previous:,.0f} -> {candidate:,.0f})"

    return candidate, None


def _allows_pot_decrease(
    previous: float,
    candidate: float,
    *,
    from_table_region: bool,
) -> bool:
    if _is_leading_dollar_misread_correction(previous, candidate):
        return True
    if from_table_region and previous >= candidate * TABLE_REGION_CORRECTION_RATIO:
        return True
    return False


def _is_leading_dollar_misread_correction(previous: float, candidate: float) -> bool:
    """Allow correcting stale pots like ``585`` or ``6190`` misread from ``$85``/``$190``."""

    previous_text = f"{int(previous)}"
    candidate_text = f"{int(candidate)}"
    if len(previous_text) <= len(candidate_text):
        return False
    if previous_text[0] not in {"5", "6"}:
        return False
    return previous_text[1:] == candidate_text
