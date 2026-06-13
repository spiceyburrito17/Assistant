"""Rule-based postflop/preflop decision engine (v2).

Designed for simple threshold logic today and optional villain-range
adjustments later via ``DecisionInputs.range_edge_adjustment``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..models import (
    DecisionConfidence,
    EquityResult,
    GameSnapshot,
    RaiseSizing,
    Recommendation,
    RecommendationLevel,
    RecommendedAction,
    SolverStatus,
    Street,
    TableStateConfidence,
)
from .decision_gate import decision_blocked_reason, gate_recommended_action


@dataclass(frozen=True)
class DecisionThresholds:
    fold_edge: float = -0.03
    raise_edge: float = 0.05
    preflop_aggression_equity: float = 0.48
    flop_aggression_equity: float = 0.55
    turn_aggression_equity: float = 0.58
    river_aggression_equity: float = 0.62


@dataclass(frozen=True)
class DecisionInputs:
    """Normalized inputs for a single decision pass."""

    snapshot: GameSnapshot
    hero_equity: float | None
    equity_warning: str | None = None
    simulations: int = 0
    range_edge_adjustment: float = 0.0


class DecisionEngine:
    """Compute pot odds, edge, action, raise sizes, and confidence for the HUD."""

    COLORS = {
        RecommendationLevel.SAFE: "#2ECC71",
        RecommendationLevel.CAUTION: "#F1C40F",
        RecommendationLevel.DANGER: "#E74C3C",
        RecommendationLevel.WAIT: "#3498DB",
        RecommendationLevel.UNKNOWN: "#95A5A6",
    }

    def __init__(self, thresholds: DecisionThresholds | None = None) -> None:
        self.thresholds = thresholds or DecisionThresholds()

    def build(
        self,
        snapshot: GameSnapshot,
        equity_result: EquityResult | None,
        *,
        solver_status: SolverStatus = SolverStatus.SKIPPED,
    ) -> Recommendation:
        inputs = self._normalize_inputs(snapshot, equity_result)
        confidence, confidence_notes = self._assess_confidence(inputs)
        required_equity = self._required_equity(snapshot)
        hero_equity = inputs.hero_equity
        edge = (
            (hero_equity - required_equity + inputs.range_edge_adjustment)
            if hero_equity is not None and required_equity is not None
            else None
        )

        blocked_reason = decision_blocked_reason(snapshot, equity_result, solver_status)
        if blocked_reason is not None:
            return self._blocked_recommendation(
                snapshot=snapshot,
                solver_status=solver_status,
                blocked_reason=blocked_reason,
                hero_equity=hero_equity,
                required_equity=required_equity,
                edge=edge,
                confidence_notes=confidence_notes,
            )

        raw_action = self._choose_action(inputs, edge, confidence)
        action, gate_reason = gate_recommended_action(raw_action, snapshot)
        if gate_reason is not None:
            return self._blocked_recommendation(
                snapshot=snapshot,
                solver_status=solver_status,
                blocked_reason=gate_reason,
                hero_equity=hero_equity,
                required_equity=required_equity,
                edge=edge,
                confidence_notes=confidence_notes,
            )

        raise_sizing = self._raise_sizing(snapshot) if action in {
            RecommendedAction.RAISE,
            RecommendedAction.BET,
        } else None
        level = self._level_for_action(action, edge, confidence)
        title = self._title_for_action(action)
        detail = self._detail_for_action(
            action=action,
            hero_equity=hero_equity,
            required_equity=required_equity,
            edge=edge,
            confidence=confidence,
            confidence_notes=confidence_notes,
            warning=inputs.equity_warning,
            raise_sizing=raise_sizing,
        )
        return Recommendation(
            level=level,
            title=title,
            detail=detail,
            color_hex=self.COLORS[level],
            action=action,
            confidence=confidence,
            confidence_notes=confidence_notes,
            equity=hero_equity,
            required_equity=required_equity,
            edge=edge,
            raise_sizing=raise_sizing,
            state_confidence=snapshot.state_confidence,
            legal_actions=snapshot.legal_actions,
            solver_status=solver_status,
            parse_diagnostics=snapshot.parse_diagnostics,
        )

    def _blocked_recommendation(
        self,
        snapshot: GameSnapshot,
        solver_status: SolverStatus,
        blocked_reason: str,
        hero_equity: float | None,
        required_equity: float | None,
        edge: float | None,
        confidence_notes: tuple[str, ...],
    ) -> Recommendation:
        notes = tuple(dict.fromkeys((*confidence_notes, blocked_reason)))
        return Recommendation(
            level=RecommendationLevel.WAIT,
            title="WAIT",
            detail=f"Decision blocked: {blocked_reason}.",
            color_hex=self.COLORS[RecommendationLevel.WAIT],
            action=RecommendedAction.WAIT,
            confidence=DecisionConfidence.LOW,
            confidence_notes=notes,
            equity=hero_equity,
            required_equity=required_equity,
            edge=edge,
            state_confidence=snapshot.state_confidence,
            legal_actions=snapshot.legal_actions,
            solver_status=solver_status,
            decision_blocked_reason=blocked_reason,
            parse_diagnostics=snapshot.parse_diagnostics,
        )

    def _normalize_inputs(
        self,
        snapshot: GameSnapshot,
        equity_result: EquityResult | None,
    ) -> DecisionInputs:
        if equity_result is None:
            return DecisionInputs(snapshot=snapshot, hero_equity=None)
        hero_equity = equity_result.hero_equity
        if hero_equity is None and equity_result.simulations == 0:
            return DecisionInputs(
                snapshot=snapshot,
                hero_equity=None,
                equity_warning=equity_result.warning,
                simulations=equity_result.simulations,
            )
        return DecisionInputs(
            snapshot=snapshot,
            hero_equity=hero_equity,
            equity_warning=equity_result.warning,
            simulations=equity_result.simulations,
        )

    def _required_equity(self, snapshot: GameSnapshot) -> float | None:
        if snapshot.to_call <= 0:
            return 0.0
        pot = snapshot.trusted_pot_size
        if pot is None:
            return None
        denominator = pot + snapshot.to_call
        if denominator <= 0:
            return None
        return max(0.0, min(1.0, snapshot.to_call / denominator))

    def _assess_confidence(
        self,
        inputs: DecisionInputs,
    ) -> tuple[DecisionConfidence, tuple[str, ...]]:
        notes: list[str] = []
        snapshot = inputs.snapshot
        if len(snapshot.hero_cards) != 2:
            notes.append("hero cards missing")
        if snapshot.street is not Street.PREFLOP and len(snapshot.board_cards) < 3:
            notes.append("board cards missing for street")
        if snapshot.trusted_pot_size is None:
            notes.append("pot unreadable")
        if snapshot.to_call < 0:
            notes.append("call amount invalid")
        if not snapshot.legal_actions:
            notes.append("legal actions missing")
        if inputs.hero_equity is None:
            notes.append("equity unavailable")
        elif inputs.simulations <= 0:
            notes.append("equity not simulated")
        if inputs.equity_warning:
            notes.append(inputs.equity_warning.lower())
        if notes:
            return DecisionConfidence.LOW, tuple(notes)
        return DecisionConfidence.HIGH, ()

    def _choose_action(
        self,
        inputs: DecisionInputs,
        edge: float | None,
        confidence: DecisionConfidence,
    ) -> RecommendedAction:
        snapshot = inputs.snapshot
        if edge is None or inputs.hero_equity is None:
            return RecommendedAction.WAIT
        if confidence is DecisionConfidence.LOW:
            return RecommendedAction.WAIT

        thresholds = self.thresholds
        if edge < thresholds.fold_edge:
            if snapshot.to_call <= 0:
                return RecommendedAction.CHECK
            return RecommendedAction.FOLD
        if edge > thresholds.raise_edge and self._supports_aggression(snapshot, inputs.hero_equity):
            if RecommendedAction.RAISE in snapshot.legal_actions:
                return RecommendedAction.RAISE
            if RecommendedAction.BET in snapshot.legal_actions:
                return RecommendedAction.BET
            return RecommendedAction.CHECK if snapshot.to_call <= 0 else RecommendedAction.CALL
        if snapshot.to_call <= 0:
            return RecommendedAction.CHECK
        return RecommendedAction.CALL

    def _supports_aggression(self, snapshot: GameSnapshot, hero_equity: float | None) -> bool:
        if hero_equity is None:
            return False
        thresholds = self.thresholds
        minimums = {
            Street.PREFLOP: thresholds.preflop_aggression_equity,
            Street.FLOP: thresholds.flop_aggression_equity,
            Street.TURN: thresholds.turn_aggression_equity,
            Street.RIVER: thresholds.river_aggression_equity,
            Street.SHOWDOWN: thresholds.river_aggression_equity,
        }
        minimum_equity = minimums.get(snapshot.street, thresholds.flop_aggression_equity)
        return hero_equity >= minimum_equity

    def _raise_sizing(self, snapshot: GameSnapshot) -> RaiseSizing:
        pot = max(snapshot.trusted_pot_size or 0.0, 0.0)
        to_call = max(snapshot.to_call, 0.0)
        pot_after_call = pot + to_call
        if to_call > 0:
            return RaiseSizing(
                min_raise=to_call * 2.0,
                half_pot=pot_after_call * 0.5,
                two_thirds_pot=pot_after_call * (2.0 / 3.0),
                pot=pot_after_call,
            )
        return RaiseSizing(
            min_raise=max(pot * 0.25, 1.0),
            half_pot=pot * 0.5,
            two_thirds_pot=pot * (2.0 / 3.0),
            pot=pot,
        )

    def _level_for_action(
        self,
        action: RecommendedAction,
        edge: float | None,
        confidence: DecisionConfidence,
    ) -> RecommendationLevel:
        if confidence is DecisionConfidence.LOW:
            return RecommendationLevel.CAUTION
        if action is RecommendedAction.WAIT:
            return RecommendationLevel.WAIT
        if action is RecommendedAction.FOLD:
            return RecommendationLevel.DANGER
        if action is RecommendedAction.RAISE:
            return RecommendationLevel.SAFE
        if edge is not None and edge >= 0.08:
            return RecommendationLevel.SAFE
        if edge is not None and edge < self.thresholds.fold_edge:
            return RecommendationLevel.DANGER
        return RecommendationLevel.CAUTION

    @staticmethod
    def _title_for_action(action: RecommendedAction) -> str:
        return {
            RecommendedAction.FOLD: "FOLD",
            RecommendedAction.CALL: "CALL",
            RecommendedAction.CHECK: "CHECK",
            RecommendedAction.RAISE: "RAISE",
            RecommendedAction.WAIT: "WAIT",
        }[action]

    def _detail_for_action(
        self,
        action: RecommendedAction,
        hero_equity: float | None,
        required_equity: float | None,
        edge: float | None,
        confidence: DecisionConfidence,
        confidence_notes: tuple[str, ...],
        warning: str | None,
        raise_sizing: RaiseSizing | None,
    ) -> str:
        parts: list[str] = []
        if hero_equity is not None and required_equity is not None and edge is not None:
            parts.append(
                f"Equity {hero_equity:.0%} vs required {required_equity:.0%} (edge {edge:+.0%})."
            )
        elif hero_equity is not None:
            parts.append(f"Equity {hero_equity:.0%}.")
        else:
            parts.append("Waiting for stable equity.")

        if action is RecommendedAction.RAISE and raise_sizing is not None:
            parts.append(
                "Sizes "
                f"min {raise_sizing.min_raise:,.0f}, "
                f"1/2 {raise_sizing.half_pot:,.0f}, "
                f"2/3 {raise_sizing.two_thirds_pot:,.0f}, "
                f"pot {raise_sizing.pot:,.0f}."
            )
        if confidence is DecisionConfidence.LOW and confidence_notes:
            parts.append(f"Low confidence: {', '.join(confidence_notes)}.")
        if warning and confidence is DecisionConfidence.HIGH:
            parts.append(warning)
        return " ".join(parts)
