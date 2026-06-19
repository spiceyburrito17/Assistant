"""HUD recommendation facade over the rule-based decision engine."""

from __future__ import annotations

from dataclasses import replace

from ..models import (
    EquityResult,
    GameSnapshot,
    Recommendation,
    RecommendationLevel,
    SolverStatus,
)
from ..poker.decision import DecisionEngine
from ..poker.equity_sanity import sanitize_equity_result


class RecommendationEngine:
    """Resolve equity snapshots into HUD-ready decision advice."""

    def __init__(self) -> None:
        self._decision_engine = DecisionEngine()

    def build(self, snapshot: GameSnapshot, result: EquityResult | None) -> Recommendation:
        if not snapshot.has_minimum_equity_inputs:
            return self._waiting(snapshot, "Waiting for stable hero cards.")
        if result is None:
            return self._waiting(snapshot, "Stable frame accepted; equity is updating.")
        if result.generation != snapshot.generation:
            if result.hero_equity is not None and abs(result.generation - snapshot.generation) <= 1:
                result = replace(result, generation=snapshot.generation)
            else:
                return self._waiting(snapshot, "Stable frame accepted; equity is updating.")
        sanitized, solver_status = sanitize_equity_result(result, snapshot)
        if sanitized.warning and sanitized.simulations == 0 and sanitized.hero_equity is None:
            block_reason = RecommendationEngine._normalize_equity_block_reason(sanitized.warning)
            return Recommendation(
                level=RecommendationLevel.UNKNOWN,
                title="UNKNOWN",
                detail=sanitized.warning,
                color_hex=DecisionEngine.COLORS[RecommendationLevel.UNKNOWN],
                state_confidence=snapshot.state_confidence,
                legal_actions=snapshot.legal_actions,
                solver_status=solver_status,
                decision_blocked_reason=block_reason,
            )
        return self._decision_engine.build(snapshot, sanitized, solver_status=solver_status)

    @staticmethod
    def _normalize_equity_block_reason(warning: str) -> str:
        lowered = warning.lower().strip()
        if "insufficient state" in lowered:
            return "insufficient_state"
        return lowered.replace(" ", "_")

    @staticmethod
    def _waiting(snapshot: GameSnapshot, detail: str) -> Recommendation:
        return Recommendation(
            level=RecommendationLevel.WAIT,
            title="WAIT",
            detail=detail,
            color_hex=DecisionEngine.COLORS[RecommendationLevel.WAIT],
            state_confidence=snapshot.state_confidence,
            legal_actions=snapshot.legal_actions,
            solver_status=SolverStatus.SKIPPED,
            parse_diagnostics=snapshot.parse_diagnostics,
        )
