"""Confidence and legal-action gates before emitting poker recommendations."""

from __future__ import annotations

from ..models import (
    EquityResult,
    GameSnapshot,
    RecommendedAction,
    SolverStatus,
    Street,
)


def decision_blocked_reason(
    snapshot: GameSnapshot,
    equity_result: EquityResult | None,
    solver_status: SolverStatus,
) -> str | None:
    parse_diag = snapshot.parse_diagnostics
    if parse_diag is not None and parse_diag.block_reason:
        if parse_diag.block_reason in {
            "pot_unreadable",
            "actions_ambiguous",
            "amount_to_call_unreadable",
            "hero_cards_unstable",
            "board_unstable",
            "legal_actions_missing",
            "post_hand",
        }:
            return parse_diag.block_reason

    if len(snapshot.hero_cards) != 2:
        return "hero_cards_unstable"
    if snapshot.street is not Street.PREFLOP and len(snapshot.board_cards) < 3:
        return "board_unstable"
    if snapshot.trusted_pot_size is None:
        return "pot_unreadable"
    if snapshot.actions_ambiguous:
        return "actions_ambiguous"
    if not snapshot.legal_actions:
        return "legal_actions_missing"
    if RecommendedAction.CALL in snapshot.legal_actions and snapshot.trusted_to_call is None:
        return "amount_to_call_unreadable"
    if snapshot.to_call < 0:
        return "amount_to_call_unreadable"
    if solver_status is SolverStatus.TIMEOUT:
        return "simulation budget hit timeout"
    if solver_status is SolverStatus.INSUFFICIENT_STATE:
        return "insufficient_state"
    if equity_result is None or equity_result.hero_equity is None:
        if snapshot.state_confidence.value == "high" and parse_diag is not None and not parse_diag.block_reason:
            return "equity_unavailable"
        return "equity unavailable"
    return None


def gate_recommended_action(
    action: RecommendedAction,
    snapshot: GameSnapshot,
) -> tuple[RecommendedAction, str | None]:
    """Ensure the chosen action is visible on the table."""

    if action is RecommendedAction.WAIT:
        return action, None
    allowed = set(snapshot.legal_actions)
    if not allowed:
        return RecommendedAction.WAIT, "legal_actions_missing"
    if action is RecommendedAction.RAISE and RecommendedAction.RAISE not in allowed:
        if RecommendedAction.BET in allowed:
            action = RecommendedAction.BET
        else:
            return RecommendedAction.WAIT, "raise not in legal_actions"
    if action is RecommendedAction.BET and RecommendedAction.BET not in allowed:
        if RecommendedAction.RAISE in allowed:
            action = RecommendedAction.RAISE
        else:
            return RecommendedAction.WAIT, "bet not in legal_actions"
    if action not in allowed:
        return RecommendedAction.WAIT, f"{action.value} not in legal_actions"
    if action is RecommendedAction.CHECK and snapshot.to_call > 0:
        return RecommendedAction.WAIT, "check unavailable while facing a bet"
    if action is RecommendedAction.CALL and RecommendedAction.CALL not in allowed:
        return RecommendedAction.WAIT, "call not in legal_actions"
    if action is RecommendedAction.CHECK and RecommendedAction.CHECK not in allowed:
        return RecommendedAction.WAIT, "check not in legal_actions"
    return action, None
