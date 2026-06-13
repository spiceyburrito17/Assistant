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
    if len(snapshot.hero_cards) != 2:
        return "hero cards missing"
    if snapshot.street is not Street.PREFLOP and len(snapshot.board_cards) < 3:
        return "board cards missing for street"
    if snapshot.trusted_pot_size is None:
        return "pot unreadable"
    if snapshot.actions_ambiguous:
        return "actions ambiguous"
    if not snapshot.legal_actions:
        return "legal actions missing"
    if snapshot.to_call < 0:
        return "call amount invalid"
    if solver_status is SolverStatus.TIMEOUT:
        return "simulation budget hit timeout"
    if solver_status is SolverStatus.INSUFFICIENT_STATE:
        return "insufficient state"
    if equity_result is None or equity_result.hero_equity is None:
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
        return RecommendedAction.WAIT, "legal actions missing"
    if action not in allowed:
        return RecommendedAction.WAIT, f"{action.value} not in legal_actions"
    if action is RecommendedAction.CHECK and snapshot.to_call > 0:
        return RecommendedAction.WAIT, "check unavailable while facing a bet"
    if action is RecommendedAction.CALL and RecommendedAction.CALL not in allowed:
        return RecommendedAction.WAIT, "call not in legal_actions"
    if action is RecommendedAction.CHECK and RecommendedAction.CHECK not in allowed:
        return RecommendedAction.WAIT, "check not in legal_actions"
    return action, None
