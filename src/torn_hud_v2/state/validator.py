"""Reject impossible or inconsistent table states."""

from __future__ import annotations

from ..models.snapshot import TableSnapshot


def validate_snapshot(snapshot: TableSnapshot) -> tuple[TableSnapshot, str | None]:
    """Return snapshot plus optional block reason when state is unusable."""

    if snapshot.post_hand_ui:
        return snapshot, "post_hand"

    if snapshot.hero_cards and len(snapshot.hero_cards) != 2:
        return _blocked(snapshot, "hero_cards_invalid")

    if len(set(snapshot.hero_cards)) != len(snapshot.hero_cards):
        return _blocked(snapshot, "hero_cards_duplicate")

    board = snapshot.board_cards
    if board and len(board) not in {3, 4, 5}:
        return _blocked(snapshot, "board_card_count_invalid")

    overlap = set(snapshot.hero_cards).intersection(snapshot.board_cards)
    if overlap:
        return _blocked(snapshot, "hero_board_overlap")

    if snapshot.pot.parsed is not None and snapshot.pot.parsed < 0:
        return _blocked(snapshot, "pot_invalid")

    if snapshot.amount_to_call.parsed is not None and snapshot.amount_to_call.parsed < 0:
        return _blocked(snapshot, "amount_to_call_invalid")

    if snapshot.hero_turn and not snapshot.legal_actions_normalized and not snapshot.post_hand_ui:
        return _blocked(snapshot, "legal_actions_missing")

    return snapshot, snapshot.block_reason


def _blocked(snapshot: TableSnapshot, reason: str) -> tuple[TableSnapshot, str]:
    from dataclasses import replace

    from ..models.snapshot import StateConfidence

    return (
        replace(snapshot, block_reason=reason, state_confidence=StateConfidence.LOW),
        reason,
    )
