"""Application orchestration for the Torn accessibility HUD."""

from __future__ import annotations

print("[DEBUG] app module import started", flush=True)

import argparse
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path

print("[DEBUG] app module importing internal components", flush=True)

from .config import AppConfig, write_default_config
from .models import ActionType, EquityRequest, EquityResult, GameSnapshot, OCRBatch, OverlayState, ParsedEvent
from .parsing.log_parser import ActionLogParser
from .poker.equity import EquityWorker
from .tracking.ledger import OpponentLedger
print("[DEBUG] app module importing TkOverlay", flush=True)
from .ui.overlay import TkOverlay
from .ui.recommendation import RecommendationEngine
print("[DEBUG] app module importing OCRWorker", flush=True)
from .vision.ocr_engine import OCRWorker

print("[DEBUG] app module import completed", flush=True)


class SnapshotBuilder:
    """Maintains current game state from validated parsed events."""

    def __init__(self, ledger: OpponentLedger) -> None:
        self.ledger = ledger
        self.snapshot = GameSnapshot()

    def apply_events(self, events: tuple[ParsedEvent, ...]) -> GameSnapshot:
        changed = False
        for event in events:
            before = self.snapshot
            self._apply_event(event)
            changed = changed or self.snapshot != before or event.player_name is not None
        if changed:
            self.snapshot = replace(
                self.snapshot,
                active_opponents=tuple(sorted(self.ledger.active_opponents)),
                opponent_stats=self.ledger.public_stats(),
                generation=self.snapshot.generation + 1,
            )
        return self.snapshot

    def _apply_event(self, event: ParsedEvent) -> None:
        if event.action is ActionType.DEALT_HERO:
            self.snapshot = GameSnapshot(hero_cards=event.cards, generation=self.snapshot.generation)
            return
        if event.action is ActionType.BOARD:
            board = self._merge_board_cards(event.cards)
            self.snapshot = replace(
                self.snapshot,
                board_cards=board,
                street=event.street or self.snapshot.street,
            )
            return
        if event.action is ActionType.POT and event.amount is not None:
            if event.raw_text.startswith("to_call"):
                self.snapshot = replace(self.snapshot, to_call=event.amount)
            else:
                self.snapshot = replace(self.snapshot, pot_size=event.amount)
            return

    def _merge_board_cards(self, cards: tuple[str, ...]) -> tuple[str, ...]:
        if len(cards) >= len(self.snapshot.board_cards):
            return cards[:5]
        merged = list(self.snapshot.board_cards)
        for card in cards:
            if card not in merged:
                merged.append(card)
        return tuple(merged[:5])


class CoordinatorWorker(threading.Thread):
    """Parse OCR batches, update tracking, and submit equity requests."""

    def __init__(
        self,
        config: AppConfig,
        ocr_queue: queue.Queue[OCRBatch],
        equity_worker: EquityWorker,
        equity_result_queue: queue.Queue[EquityResult],
        overlay: TkOverlay,
    ) -> None:
        super().__init__(name="torn-coordinator-worker", daemon=True)
        self.config = config
        self.ocr_queue = ocr_queue
        self.equity_worker = equity_worker
        self.equity_result_queue = equity_result_queue
        self.overlay = overlay
        self.stop_event = threading.Event()
        self.parser = ActionLogParser(config.parser)
        self.ledger = OpponentLedger()
        self.builder = SnapshotBuilder(self.ledger)
        self.recommendations = RecommendationEngine()
        self.latest_lines: tuple[str, ...] = ()
        self.latest_equity: EquityResult | None = None
        self.last_submitted_generation = -1

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        self._publish()
        while not self.stop_event.is_set():
            self._drain_ocr()
            self._drain_equity()
            self._submit_equity_if_needed()
            self._publish()
            self.stop_event.wait(0.05)

    def _drain_ocr(self) -> None:
        latest: OCRBatch | None = None
        while True:
            try:
                latest = self.ocr_queue.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        self.latest_lines = tuple(line.text for line in latest.lines)
        events = self.parser.parse_lines(latest.lines)
        if not events:
            return
        self.ledger.process_events(events)
        self.builder.apply_events(events)

    def _drain_equity(self) -> None:
        while True:
            try:
                result = self.equity_result_queue.get_nowait()
            except queue.Empty:
                break
            if result.generation >= self.builder.snapshot.generation:
                self.latest_equity = result

    def _submit_equity_if_needed(self) -> None:
        snapshot = self.builder.snapshot
        if not snapshot.has_minimum_equity_inputs:
            return
        if snapshot.generation == self.last_submitted_generation:
            return
        self.last_submitted_generation = snapshot.generation
        self.equity_worker.submit(
            EquityRequest(
                snapshot=snapshot,
                opponent_range_weights=self.ledger.range_weight_snapshot(),
                simulations=self.config.equity.simulations,
                timeout_ms=self.config.equity.timeout_ms,
            )
        )

    def _publish(self) -> None:
        snapshot = self.builder.snapshot
        recommendation = self.recommendations.build(snapshot, self.latest_equity)
        diagnostics = {}
        if self.equity_worker.last_error:
            diagnostics["equity_error"] = self.equity_worker.last_error
        self.overlay.publish(
            OverlayState(
                snapshot=snapshot,
                recommendation=recommendation,
                latest_lines=self.latest_lines,
                equity_result=self.latest_equity,
                diagnostics=diagnostics,
            )
        )


class TornHudApplication:
    """Owns lifecycle for all background components."""

    def __init__(self, config: AppConfig) -> None:
        print("[DEBUG] app startup: instantiating components", flush=True)
        self.config = config
        print("[DEBUG] app startup: AppConfig assigned", flush=True)
        self.ocr_queue: queue.Queue[OCRBatch] = queue.Queue(maxsize=config.ocr.queue_size)
        print("[DEBUG] app startup: OCR queue created", flush=True)
        self.equity_request_queue: queue.Queue[EquityRequest] = queue.Queue(maxsize=1)
        print("[DEBUG] app startup: Equity request queue created", flush=True)
        self.equity_result_queue: queue.Queue[EquityResult] = queue.Queue(maxsize=1)
        print("[DEBUG] app startup: Equity result queue created", flush=True)
        self.overlay = TkOverlay(config.overlay)
        print("[DEBUG] app startup: TkOverlay created", flush=True)
        self.ocr_worker = OCRWorker(config, self.ocr_queue)
        print("[DEBUG] app startup: OCRWorker created", flush=True)
        self.equity_worker = EquityWorker(
            self.equity_request_queue,
            self.equity_result_queue,
            seed=config.equity.random_seed,
        )
        print("[DEBUG] app startup: EquityWorker created", flush=True)
        self.coordinator = CoordinatorWorker(
            config,
            self.ocr_queue,
            self.equity_worker,
            self.equity_result_queue,
            self.overlay,
        )
        print("[DEBUG] app startup: CoordinatorWorker created", flush=True)

    def run(self) -> None:
        print("[DEBUG] app startup: starting worker threads", flush=True)
        print(f"[DEBUG] Starting thread: {_describe_thread(self.ocr_worker)}", flush=True)
        self.ocr_worker.start()
        print(f"[DEBUG] Starting thread: {_describe_thread(self.equity_worker)}", flush=True)
        self.equity_worker.start()
        print(f"[DEBUG] Starting thread: {_describe_thread(self.coordinator)}", flush=True)
        self.coordinator.start()
        try:
            print("[DEBUG] app startup: starting TkOverlay mainloop component", flush=True)
            self.overlay.start()
        finally:
            self.stop()

    def stop(self) -> None:
        self.ocr_worker.stop()
        self.equity_worker.stop()
        self.coordinator.stop()
        for worker in (self.ocr_worker, self.equity_worker, self.coordinator):
            worker.join(timeout=1.0)


def _describe_thread(thread: threading.Thread) -> str:
    target = getattr(thread, "_target", None)
    target_name = getattr(target, "__qualname__", repr(target)) if target is not None else "<Thread.run override>"
    return (
        f"class={thread.__class__.__name__} name={thread.name} "
        f"daemon={thread.daemon} target={target_name}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Torn City accessibility HUD.")
    parser.add_argument("--config", type=Path, default=Path("config/default_config.json"), help="Path to JSON config.")
    parser.add_argument(
        "--write-default-config",
        type=Path,
        help="Write a default JSON config to the provided path and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    print("[DEBUG] app.main() entered", flush=True)
    args = build_arg_parser().parse_args(argv)
    print(f"[DEBUG] app.main() parsed args config={args.config}", flush=True)
    if args.write_default_config:
        path = write_default_config(args.write_default_config)
        print(f"Wrote default config to {path}")
        return 0
    config = AppConfig.load(args.config if args.config.exists() else None)
    print("[DEBUG] app.main() AppConfig loaded", flush=True)
    app = TornHudApplication(config)
    print("[DEBUG] app.main() TornHudApplication created", flush=True)
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
