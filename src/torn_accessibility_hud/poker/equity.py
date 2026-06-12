"""Threaded Monte Carlo equity calculation using Treys."""

from __future__ import annotations

import queue
import random
import threading
import time
from typing import Mapping

from ..models import EquityRequest, EquityResult, GameSnapshot
from ..parsing.cards import FULL_DECK, validate_cards
from ..tracking.range_matrix import RangeMatrix


class MonteCarloEquityCalculator:
    """Synchronous calculator; use EquityWorker for UI-safe execution."""

    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed

    def calculate(
        self,
        snapshot: GameSnapshot,
        opponent_range_weights: Mapping[str, Mapping[str, float]],
        simulations: int,
        timeout_ms: int,
    ) -> EquityResult:
        started = time.monotonic()
        if not snapshot.has_minimum_equity_inputs:
            return EquityResult(0.0, 0.0, 0, snapshot.generation, 0.0, "hero cards missing")
        visible_cards = tuple(snapshot.hero_cards) + tuple(snapshot.board_cards)
        dead_cards = set(visible_cards)
        if not validate_cards(visible_cards, max_cards=7):
            return EquityResult(0.0, 0.0, 0, snapshot.generation, 0.0, "invalid or duplicate cards")
        opponents = tuple(snapshot.active_opponents)
        if not opponents:
            return EquityResult(1.0, 0.0, 0, snapshot.generation, 0.0, "no active opponents")

        from treys import Card, Evaluator

        evaluator = Evaluator()
        rng_seed = self.seed if self.seed is not None else time.time_ns()
        rng = random.Random(rng_seed + snapshot.generation)
        hero_cards = [Card.new(card) for card in snapshot.hero_cards]
        board_cards = list(snapshot.board_cards)
        wins = 0.0
        ties = 0
        completed = 0
        warning: str | None = None
        matrices = {
            name: RangeMatrix.from_weights(opponent_range_weights.get(name, {})) for name in opponents
        }

        for _ in range(max(simulations, 1)):
            if (time.monotonic() - started) * 1000.0 >= timeout_ms and completed > 0:
                warning = "simulation budget hit timeout"
                break
            excluded = set(dead_cards)
            opponent_hands: list[tuple[str, str]] = []
            for name in opponents:
                combo = matrices[name].sample_combo(excluded, rng)
                if combo is None:
                    warning = f"not enough cards to sample {name}"
                    break
                opponent_hands.append(combo)
                excluded.update(combo)
            if warning and len(opponent_hands) != len(opponents):
                break

            runout = list(board_cards)
            needed = 5 - len(runout)
            deck = [card for card in FULL_DECK if card not in excluded]
            if needed < 0 or len(deck) < needed:
                warning = "invalid board/deck state"
                break
            runout.extend(rng.sample(deck, needed))
            treys_board = [Card.new(card) for card in runout]
            hero_score = evaluator.evaluate(treys_board, hero_cards)
            opponent_scores = [
                evaluator.evaluate(treys_board, [Card.new(first), Card.new(second)])
                for first, second in opponent_hands
            ]
            best_score = min([hero_score, *opponent_scores])
            if hero_score == best_score:
                tied_winners = 1 + sum(score == best_score for score in opponent_scores)
                wins += 1.0 / tied_winners
                if tied_winners > 1:
                    ties += 1
            completed += 1

        elapsed_ms = (time.monotonic() - started) * 1000.0
        if completed == 0:
            return EquityResult(0.0, 0.0, 0, snapshot.generation, elapsed_ms, warning or "no simulations completed")
        return EquityResult(
            hero_equity=max(0.0, min(1.0, wins / completed)),
            tie_rate=ties / completed,
            simulations=completed,
            generation=snapshot.generation,
            elapsed_ms=elapsed_ms,
            warning=warning,
        )


class EquityWorker(threading.Thread):
    """Latest-only equity worker for Tkinter-safe Monte Carlo simulation."""

    def __init__(
        self,
        request_queue: queue.Queue[EquityRequest],
        result_queue: queue.Queue[EquityResult],
        seed: int | None = None,
    ) -> None:
        super().__init__(name="torn-equity-worker", daemon=True)
        self.request_queue = request_queue
        self.result_queue = result_queue
        self.stop_event = threading.Event()
        self.calculator = MonteCarloEquityCalculator(seed=seed)
        self.last_error: str | None = None

    def stop(self) -> None:
        self.stop_event.set()

    def submit(self, request: EquityRequest) -> None:
        while True:
            try:
                self.request_queue.put_nowait(request)
                return
            except queue.Full:
                try:
                    self.request_queue.get_nowait()
                except queue.Empty:
                    return

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                request = self.request_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            while True:
                try:
                    request = self.request_queue.get_nowait()
                except queue.Empty:
                    break
            try:
                result = self.calculator.calculate(
                    request.snapshot,
                    request.opponent_range_weights,
                    request.simulations,
                    request.timeout_ms,
                )
                self._put_latest_result(result)
            except Exception as exc:  # noqa: BLE001 - keep UI alive on math/runtime anomalies
                self.last_error = f"{type(exc).__name__}: {exc}"

    def _put_latest_result(self, result: EquityResult) -> None:
        while True:
            try:
                self.result_queue.put_nowait(result)
                return
            except queue.Full:
                try:
                    self.result_queue.get_nowait()
                except queue.Empty:
                    return
