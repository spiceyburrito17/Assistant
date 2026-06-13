"""Color-coded accessibility recommendation logic."""

from __future__ import annotations

from ..models import EquityResult, GameSnapshot, Recommendation, RecommendationLevel


class RecommendationEngine:
    """Translate equity and pot odds into dyslexia-friendly visual states."""

    COLORS = {
        RecommendationLevel.SAFE: "#2ECC71",
        RecommendationLevel.CAUTION: "#F1C40F",
        RecommendationLevel.DANGER: "#E74C3C",
        RecommendationLevel.WAIT: "#3498DB",
        RecommendationLevel.UNKNOWN: "#95A5A6",
    }

    def build(self, snapshot: GameSnapshot, result: EquityResult | None) -> Recommendation:
        if not snapshot.has_minimum_equity_inputs:
            return Recommendation(
                level=RecommendationLevel.WAIT,
                title="WAIT",
                detail="Waiting for stable hero cards.",
                color_hex=self.COLORS[RecommendationLevel.WAIT],
            )
        if result is None or result.generation != snapshot.generation:
            return Recommendation(
                level=RecommendationLevel.WAIT,
                title="READING",
                detail="Stable frame accepted; equity is updating.",
                color_hex=self.COLORS[RecommendationLevel.WAIT],
            )
        if result.warning and result.simulations == 0:
            if result.hero_equity is None:
                return Recommendation(
                    level=RecommendationLevel.CAUTION,
                    title="DEALING",
                    detail=result.warning,
                    color_hex=self.COLORS[RecommendationLevel.CAUTION],
                )
            return Recommendation(
                level=RecommendationLevel.UNKNOWN,
                title="UNKNOWN",
                detail=result.warning,
                color_hex=self.COLORS[RecommendationLevel.UNKNOWN],
            )

        equity = result.hero_equity
        if equity is None:
            return Recommendation(
                level=RecommendationLevel.CAUTION,
                title="WAITING",
                detail=result.warning or "Equity is temporarily unavailable.",
                color_hex=self.COLORS[RecommendationLevel.CAUTION],
            )
        pot_odds = self._pot_odds(snapshot)
        edge = equity - pot_odds
        if snapshot.to_call <= 0:
            level = RecommendationLevel.SAFE if equity >= 0.33 else RecommendationLevel.CAUTION
            title = "FREE / CHECK"
            detail = f"Equity {equity:.0%}; no call cost detected."
        elif edge >= 0.08:
            level = RecommendationLevel.SAFE
            title = "GOOD ODDS"
            detail = f"Equity {equity:.0%} beats pot odds {pot_odds:.0%}."
        elif edge >= -0.03:
            level = RecommendationLevel.CAUTION
            title = "CLOSE"
            detail = f"Equity {equity:.0%} is near pot odds {pot_odds:.0%}."
        else:
            level = RecommendationLevel.DANGER
            title = "BAD ODDS"
            detail = f"Equity {equity:.0%} trails pot odds {pot_odds:.0%}."
        if result.warning:
            detail = f"{detail} ({result.warning})"
        return Recommendation(
            level=level,
            title=title,
            detail=detail,
            color_hex=self.COLORS[level],
            equity=equity,
            pot_odds=pot_odds,
        )

    @staticmethod
    def _pot_odds(snapshot: GameSnapshot) -> float:
        if snapshot.to_call <= 0:
            return 0.0
        denominator = snapshot.pot_size + snapshot.to_call
        if denominator <= 0:
            return 1.0
        return max(0.0, min(1.0, snapshot.to_call / denominator))
