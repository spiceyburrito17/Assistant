"""HUD recommendation facade over the rule-based decision engine."""

from __future__ import annotations

from dataclasses import replace

from ..models import EquityResult, GameSnapshot, Recommendation, RecommendationLevel
from ..poker.decision import DecisionEngine


class RecommendationEngine:
    """Resolve equity snapshots into HUD-ready decision advice."""

    def __init__(self) -> None:
        self._decision_engine = DecisionEngine()

    def build(self, snapshot: GameSnapshot, result: EquityResult | None) -> Recommendation:
        if not snapshot.has_minimum_equity_inputs:
            return self._waiting("Waiting for stable hero cards.")
        if result is None:
            return self._waiting("Stable frame accepted; equity is updating.")
        if result.generation != snapshot.generation:
            if result.hero_equity is not None and abs(result.generation - snapshot.generation) <= 1:
                result = replace(result, generation=snapshot.generation)
            else:
                return self._waiting("Stable frame accepted; equity is updating.")
        if result.warning and result.simulations == 0 and result.hero_equity is None:
            return Recommendation(
                level=RecommendationLevel.UNKNOWN,
                title="UNKNOWN",
                detail=result.warning,
                color_hex=DecisionEngine.COLORS[RecommendationLevel.UNKNOWN],
            )
        return self._decision_engine.build(snapshot, result)

    @staticmethod
    def _waiting(detail: str) -> Recommendation:
        return Recommendation(
            level=RecommendationLevel.WAIT,
            title="WAIT",
            detail=detail,
            color_hex=DecisionEngine.COLORS[RecommendationLevel.WAIT],
        )
