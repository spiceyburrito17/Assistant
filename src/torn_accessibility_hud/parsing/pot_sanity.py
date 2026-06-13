"""Sanity checks for trusted pot updates within a hand."""

from __future__ import annotations

MAX_REASONABLE_POT = 10_000_000.0
MAX_POT_JUMP_RATIO = 12.0


def validate_pot_update(
    candidate: float,
    *,
    previous: float | None,
    hand_reset: bool,
) -> tuple[float | None, str | None]:
    """Accept or reject a parsed pot relative to the last trusted value."""

    if candidate <= 0 or candidate > MAX_REASONABLE_POT:
        return None, "absurd magnitude"

    if hand_reset or previous is None:
        return candidate, None

    if candidate < previous:
        return None, "pot decreased within hand"

    if candidate > previous * MAX_POT_JUMP_RATIO:
        return None, f"pot jump too large ({previous:,.0f} -> {candidate:,.0f})"

    return candidate, None
