"""Application orchestration for the Torn accessibility HUD."""

from __future__ import annotations

import argparse
import queue
import threading
import time
from dataclasses import replace
from pathlib import Path

from .diagnostics import configure_runtime_logging, debug_log, write_startup_log

configure_runtime_logging()
write_startup_log("app module import started")
debug_log("app module import started")
debug_log("app module importing internal components")

from .config import AppConfig, write_default_config
from .debug_session_csv import SessionDebugCSVLogger, SessionDebugEventTracker
from .models import ActionType, EquityRequest, EquityResult, GameSnapshot, OCRBatch, OverlayState, ParsedEvent, Street
from .parsing.log_parser import ActionLogParser
from .poker.equity import EquityWorker
from .state import TrustedTableStateManager
from .tracking.ledger import OpponentLedger
debug_log("app module importing TkOverlay")
from .ui.overlay import TkOverlay
from .ui.recommendation import RecommendationEngine
debug_log("app module importing OCRWorker")
from .vision.ocr_engine import OCRWorker

debug_log("app module import completed")


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
            if event.cards == self.snapshot.hero_cards:
                return
            self.snapshot = replace(
                self.snapshot,
                hero_cards=event.cards,
                board_cards=(),
                street=Street.PREFLOP,
                generation=self.snapshot.generation + 1,
            )
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
        self.trusted_state = TrustedTableStateManager(
            hero_missing_grace_scans=config.ocr.card_cache_max_missing_scans,
            board_regress_scans=max(config.ocr.card_cache_max_missing_scans // 2, 8),
        )
        self._last_published: OverlayState | None = None
        self.recommendations = RecommendationEngine()
        self.latest_lines: tuple[str, ...] = ()
        self.latest_equity: EquityResult | None = None
        self.last_submitted_generation = -1
        self._session_debug_tracker: SessionDebugEventTracker | None = None
        if config.debug.session_csv_enabled:
            session_logger = SessionDebugCSVLogger(config.debug.session_csv_path)
            self._session_debug_tracker = SessionDebugEventTracker(session_logger)
            write_startup_log(
                f"app startup: session debug CSV reset at {config.debug.session_csv_path}"
            )
            debug_log(
                "app startup: session debug CSV reset at %s",
                config.debug.session_csv_path,
            )

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
        if events:
            self.ledger.process_events(events)
            self.builder.apply_events(events)
        trusted, snapshot = self.trusted_state.apply(
            self.builder.snapshot,
            events,
            self.latest_lines,
            hero_region_folded=latest.hero_region_folded,
            hero_cards_scanned=latest.hero_cards_scanned,
            board_cards_scanned=latest.board_cards_scanned,
            hero_cards_stable=latest.hero_cards_stable,
            board_cards_stable=latest.board_cards_stable,
            table_ocr=latest.table_ocr,
        )
        if snapshot != self.builder.snapshot:
            self.builder.snapshot = snapshot
            if self.latest_equity is not None and self.latest_equity.generation != snapshot.generation:
                self.latest_equity = None

    def _drain_equity(self) -> None:
        snapshot_generation = self.builder.snapshot.generation
        while True:
            try:
                result = self.equity_result_queue.get_nowait()
            except queue.Empty:
                break
            if result.generation == snapshot_generation:
                self.latest_equity = result
            elif result.generation <= snapshot_generation and (
                self.latest_equity is None or result.generation > self.latest_equity.generation
            ):
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
        trusted = self.trusted_state.trusted
        recommendation = self.recommendations.build(snapshot, self.latest_equity)
        parse_diag = snapshot.parse_diagnostics or trusted.parse_diagnostics
        diagnostics = {
            "state_confidence": trusted.state_confidence.value,
            "legal_actions": ",".join(action.value for action in trusted.legal_actions) or "--",
            "solver_status": recommendation.solver_status.value,
        }
        if parse_diag is not None:
            diagnostics["pot_crop_text"] = parse_diag.pot_crop_text or parse_diag.pot_raw or "--"
            diagnostics["pot_anchor_match"] = parse_diag.pot_anchor_match or "--"
            diagnostics["pot_anchor_confidence"] = (
                f"{parse_diag.pot_anchor_confidence:.2f}"
                if parse_diag.pot_anchor_confidence is not None
                else "--"
            )
            diagnostics["pot_digits_start"] = (
                str(parse_diag.pot_digits_start) if parse_diag.pot_digits_start is not None else "--"
            )
            diagnostics["pot_candidate"] = parse_diag.pot_candidate or "--"
            diagnostics["pot_normalized"] = (
                f"{parse_diag.pot_normalized:,.0f}"
                if parse_diag.pot_normalized is not None
                else "--"
            )
            if parse_diag.pot_rejected_reason:
                diagnostics["pot_rejected_reason"] = parse_diag.pot_rejected_reason
            diagnostics["legal_actions_raw"] = "|".join(parse_diag.legal_actions_raw) or "--"
            diagnostics["legal_actions_normalized"] = ",".join(parse_diag.legal_actions_normalized) or "--"
            diagnostics["amount_to_call_raw"] = parse_diag.amount_to_call_raw or "--"
            diagnostics["amount_to_call_parsed"] = (
                f"{parse_diag.amount_to_call_parsed:,.0f}"
                if parse_diag.amount_to_call_parsed is not None
                else "--"
            )
            diagnostics["slot_left_raw"] = parse_diag.slot_left_raw or "--"
            diagnostics["slot_centre_raw"] = parse_diag.slot_centre_raw or "--"
            diagnostics["slot_right_raw"] = parse_diag.slot_right_raw or "--"
            diagnostics["slot_left_coords"] = parse_diag.slot_left_coords or "--"
            diagnostics["slot_centre_coords"] = parse_diag.slot_centre_coords or "--"
            diagnostics["slot_right_coords"] = parse_diag.slot_right_coords or "--"
            diagnostics["post_hand_ui"] = "true" if parse_diag.post_hand_ui else "false"
            if parse_diag.block_reason:
                diagnostics["block_reason"] = parse_diag.block_reason
        block_reason = recommendation.decision_blocked_reason or (
            parse_diag.block_reason if parse_diag is not None else None
        )
        if block_reason:
            diagnostics["decision_blocked_reason"] = block_reason
        if self.equity_worker.last_error:
            diagnostics["equity_error"] = self.equity_worker.last_error
        if self.latest_equity is not None:
            diagnostics["equity_simulations"] = str(self.latest_equity.simulations)
            if self.latest_equity.warning:
                diagnostics["equity_warning"] = self.latest_equity.warning
        state = OverlayState(
            snapshot=snapshot,
            recommendation=recommendation,
            latest_lines=self.latest_lines,
            equity_result=self.latest_equity,
            diagnostics=diagnostics,
        )
        if self._last_published is not None and self._overlay_state_unchanged(self._last_published, state):
            return
        self._last_published = state
        self.overlay.publish(state)
        if self._session_debug_tracker is not None:
            self._session_debug_tracker.observe(snapshot, recommendation)

    @staticmethod
    def _overlay_state_unchanged(previous: OverlayState, current: OverlayState) -> bool:
        return (
            previous.snapshot == current.snapshot
            and previous.recommendation == current.recommendation
            and previous.latest_lines == current.latest_lines
            and previous.equity_result == current.equity_result
            and dict(previous.diagnostics) == dict(current.diagnostics)
        )


class TornHudApplication:
    """Owns lifecycle for all background components."""

    def __init__(self, config: AppConfig) -> None:
        write_startup_log("app startup: instantiating components")
        debug_log("app startup: instantiating components")
        self.config = config
        write_startup_log("app startup: AppConfig assigned")
        debug_log("app startup: AppConfig assigned")
        self.ocr_queue: queue.Queue[OCRBatch] = queue.Queue(maxsize=config.ocr.queue_size)
        write_startup_log("app startup: OCR queue created")
        debug_log("app startup: OCR queue created")
        self.equity_request_queue: queue.Queue[EquityRequest] = queue.Queue(maxsize=1)
        write_startup_log("app startup: Equity request queue created")
        debug_log("app startup: Equity request queue created")
        self.equity_result_queue: queue.Queue[EquityResult] = queue.Queue(maxsize=1)
        write_startup_log("app startup: Equity result queue created")
        debug_log("app startup: Equity result queue created")
        self.overlay = TkOverlay(config.overlay)
        write_startup_log("app startup: TkOverlay created")
        debug_log("app startup: TkOverlay created")
        self.ocr_worker = OCRWorker(config, self.ocr_queue)
        write_startup_log("app startup: OCRWorker created")
        debug_log("app startup: OCRWorker created")
        self.equity_worker = EquityWorker(
            self.equity_request_queue,
            self.equity_result_queue,
            seed=config.equity.random_seed,
        )
        write_startup_log("app startup: EquityWorker created")
        debug_log("app startup: EquityWorker created")
        self.coordinator = CoordinatorWorker(
            config,
            self.ocr_queue,
            self.equity_worker,
            self.equity_result_queue,
            self.overlay,
        )
        write_startup_log("app startup: CoordinatorWorker created")
        debug_log("app startup: CoordinatorWorker created")

    def run(self) -> None:
        write_startup_log("app startup: starting worker threads")
        debug_log("app startup: starting worker threads")
        debug_log("Starting thread: %s", _describe_thread(self.ocr_worker))
        self.ocr_worker.start()
        debug_log("Starting thread: %s", _describe_thread(self.equity_worker))
        self.equity_worker.start()
        debug_log("Starting thread: %s", _describe_thread(self.coordinator))
        self.coordinator.start()
        try:
            write_startup_log("app startup: starting TkOverlay mainloop component")
            debug_log("app startup: starting TkOverlay mainloop component")
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


def _format_region_for_log(region: object) -> str:
    if region is None:
        return "<none>"
    left = getattr(region, "left", "?")
    top = getattr(region, "top", "?")
    width = getattr(region, "width", "?")
    height = getattr(region, "height", "?")
    return f"left={left} top={top} width={width} height={height}"


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
    configure_runtime_logging()
    write_startup_log("app.main() entered")
    debug_log("app.main() entered")
    args = build_arg_parser().parse_args(argv)
    write_startup_log(f"app.main() parsed args config={args.config}")
    debug_log("app.main() parsed args config=%s", args.config)
    if args.write_default_config:
        path = write_default_config(args.write_default_config)
        print(f"Wrote default config to {path}")
        return 0
    config = AppConfig.load(args.config if args.config.exists() else None)
    write_startup_log("app.main() AppConfig loaded")
    debug_log("app.main() AppConfig loaded")
    debug_log("config ocr.hero_cards_region: %s", _format_region_for_log(config.ocr.hero_cards_region))
    debug_log("config ocr.board_cards_region: %s", _format_region_for_log(config.ocr.board_cards_region))
    app = TornHudApplication(config)
    write_startup_log("app.main() TornHudApplication created")
    debug_log("app.main() TornHudApplication created")
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
