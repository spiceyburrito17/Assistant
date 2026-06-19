"""Event-driven v2 application orchestrator."""

from __future__ import annotations

import queue
import threading
import time

from .bridge.receiver import MessageQueueBridge, WebSocketReceiver
from .config import HudConfig
from .debug.csv_logger import SessionCSVLogger
from .decision.engine import DecisionEngine
from .models.messages import TableDeltaMessage
from .overlay.hud import HudOverlay, OverlayUpdate
from .state.container import TableStateContainer
from .state.machine import TableStateMachine


class HudApplication:
    """Local passive HUD: receive DOM deltas, normalize, log CSV, show overlay."""

    def __init__(self, config: HudConfig) -> None:
        self.config = config
        self.stop_event = threading.Event()
        self.message_queue: queue.Queue[TableDeltaMessage] = queue.Queue(maxsize=32)
        self.csv_logger = SessionCSVLogger(config.session_csv_path)
        self.state_container = TableStateContainer()
        self.state_machine = TableStateMachine(self.csv_logger)
        self.decision_engine = DecisionEngine()
        self.overlay = HudOverlay()
        self.receiver = WebSocketReceiver(
            MessageQueueBridge(self.message_queue),
            host=config.ws_host,
            port=config.ws_port,
        )
        self._coordinator = threading.Thread(target=self._run_coordinator, name="torn-hud-v2-coordinator", daemon=True)

    def run(self) -> None:
        self.overlay.start()
        self.receiver.start()
        self._coordinator.start()
        try:
            while not self.stop_event.is_set():
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        self.receiver.stop()
        self.overlay.stop()
        self._coordinator.join(timeout=1.0)

    def _run_coordinator(self) -> None:
        while not self.stop_event.is_set():
            self._drain_messages()
            time.sleep(self.config.poll_interval_sec)

    def _drain_messages(self) -> None:
        latest: TableDeltaMessage | None = None
        while True:
            try:
                latest = self.message_queue.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return

        snapshot, _block_reason = self.state_container.apply_message(latest)
        recommendation = self.decision_engine.recommend(snapshot)
        self.state_machine.apply(snapshot, recommendation)
        diagnostics = {
            "bridge_clients": str(self.receiver.client_count),
            "bridge_messages": str(self.receiver.messages_received),
            "seq": str(snapshot.seq),
            "extract_sources": snapshot.extract_sources or "--",
            "hero_stack": str(snapshot.hero_stack.parsed if snapshot.hero_stack.parsed is not None else "--"),
        }
        if self.receiver.last_error:
            diagnostics["bridge_error"] = self.receiver.last_error
        self.overlay.publish(
            OverlayUpdate(snapshot=snapshot, recommendation=recommendation, diagnostics=diagnostics)
        )
