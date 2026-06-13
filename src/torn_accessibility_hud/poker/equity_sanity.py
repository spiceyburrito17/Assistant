"""Sanitize raw Monte Carlo output before it reaches the decision engine."""

from __future__ import annotations

from dataclasses import replace

from ..models import EquityResult, GameSnapshot, SolverStatus


def classify_solver_status(result: EquityResult, snapshot: GameSnapshot) -> SolverStatus:
    warning = (result.warning or "").lower()
    if result.simulations <= 0:
        if "insufficient state" in warning or "no active opponents" in warning:
            return SolverStatus.INSUFFICIENT_STATE
        if "awaiting full flop" in warning or "invalid board" in warning:
            return SolverStatus.SKIPPED
        return SolverStatus.SKIPPED
    if "timeout" in warning:
        return SolverStatus.TIMEOUT
    if not snapshot.active_opponents:
        return SolverStatus.INSUFFICIENT_STATE
    return SolverStatus.OK


def sanitize_equity_result(result: EquityResult, snapshot: GameSnapshot) -> tuple[EquityResult, SolverStatus]:
    """Drop degenerate 100% reads and attach solver status metadata."""

    status = classify_solver_status(result, snapshot)
    hero_equity = result.hero_equity

    if status is SolverStatus.INSUFFICIENT_STATE:
        hero_equity = None
    elif hero_equity is not None and hero_equity >= 0.999:
        if status is not SolverStatus.OK or result.simulations < 100 or not snapshot.active_opponents:
            hero_equity = None
            status = SolverStatus.INSUFFICIENT_STATE
    elif status is SolverStatus.TIMEOUT:
        hero_equity = None

    if hero_equity is None and status is SolverStatus.OK:
        status = SolverStatus.SKIPPED

    sanitized = replace(result, hero_equity=hero_equity)
    return sanitized, status
