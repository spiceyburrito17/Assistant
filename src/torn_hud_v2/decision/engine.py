"""Placeholder recommendation engine for the v2 vertical slice."""

from __future__ import annotations

from ..models.snapshot import (
    RecommendationView,
    RecommendedAction,
    SolverStatus,
    StateConfidence,
    TableSnapshot,
)


class DecisionEngine:
    """Stub decision logic — validates pipeline wiring before real solver integration."""

    def recommend(self, snapshot: TableSnapshot) -> RecommendationView:
        if snapshot.block_reason:
            return RecommendationView(
                action=RecommendedAction.WAIT,
                detail=f"Blocked: {snapshot.block_reason}",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.BLOCKED,
                block_reason=snapshot.block_reason,
            )

        if not snapshot.hero_turn:
            return RecommendationView(
                action=RecommendedAction.WAIT,
                detail="Waiting for hero turn.",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.SKIPPED,
            )

        if snapshot.state_confidence is StateConfidence.LOW:
            return RecommendationView(
                action=RecommendedAction.WAIT,
                detail="Low-confidence table state.",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.SKIPPED,
                block_reason="insufficient_state",
            )

        actions = set(snapshot.legal_actions_normalized)
        if "check" in actions:
            return RecommendationView(
                action=RecommendedAction.CHECK,
                detail="Stub: free check available.",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.OK,
            )
        if "call" in actions:
            return RecommendationView(
                action=RecommendedAction.CALL,
                detail="Stub: facing a bet with call available.",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.OK,
            )
        if "fold" in actions:
            return RecommendationView(
                action=RecommendedAction.FOLD,
                detail="Stub: only fold available.",
                state_confidence=snapshot.state_confidence,
                solver_status=SolverStatus.OK,
            )

        return RecommendationView(
            action=RecommendedAction.WAIT,
            detail="Stub: no mapped action.",
            state_confidence=snapshot.state_confidence,
            solver_status=SolverStatus.SKIPPED,
            block_reason="legal_actions_missing",
        )
