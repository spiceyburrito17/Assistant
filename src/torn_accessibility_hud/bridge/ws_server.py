"""Local WebSocket server that ingests deterministic table state from the userscript."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any

from ..diagnostics import debug_log, exception_log, write_startup_log

from .payload import BridgeTableUpdate, GameStatePayload

DEFAULT_BRIDGE_HOST = "localhost"
DEFAULT_BRIDGE_PORT = 8765


class PokerWebSocketBridge:
    """Run ``websockets`` on a background thread and push parsed payloads to a queue."""

    def __init__(
        self,
        output_queue: queue.Queue[BridgeTableUpdate],
        *,
        host: str = DEFAULT_BRIDGE_HOST,
        port: int = DEFAULT_BRIDGE_PORT,
        queue_size: int = 8,
    ) -> None:
        self.output_queue = output_queue
        self.host = host
        self.port = port
        self.queue_size = max(queue_size, 1)
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None
        self._sequence = 0
        self._clients = 0
        self.last_error: str | None = None
        self.last_payload: GameStatePayload | None = None
        self.messages_received = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="torn-poker-ws-bridge",
            daemon=True,
        )
        write_startup_log(
            f"PokerWebSocketBridge starting on ws://{self.host}:{self.port}"
        )
        debug_log("PokerWebSocketBridge starting on ws://%s:%s", self.host, self.port)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: None)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def client_count(self) -> int:
        return self._clients

    def _run_event_loop(self) -> None:
        try:
            asyncio.run(self._serve_forever())
        except Exception as exc:  # noqa: BLE001 - keep bridge thread from killing the app
            self.last_error = f"{type(exc).__name__}: {exc}"
            exception_log("PokerWebSocketBridge crashed: %s", exc)

    async def _serve_forever(self) -> None:
        import websockets
        from websockets.server import WebSocketServerProtocol

        self._loop = asyncio.get_running_loop()

        async def handler(websocket: WebSocketServerProtocol) -> None:
            self._clients += 1
            debug_log("PokerWebSocketBridge client connected (%s active)", self._clients)
            try:
                async for message in websocket:
                    self._handle_message(message)
            except Exception as exc:  # noqa: BLE001 - one bad client must not stop the server
                self.last_error = f"{type(exc).__name__}: {exc}"
                exception_log("PokerWebSocketBridge client error: %s", exc)
            finally:
                self._clients -= 1
                debug_log("PokerWebSocketBridge client disconnected (%s active)", self._clients)

        async with websockets.serve(handler, self.host, self.port):
            write_startup_log(
                f"PokerWebSocketBridge listening on ws://{self.host}:{self.port}"
            )
            debug_log("PokerWebSocketBridge listening on ws://%s:%s", self.host, self.port)
            while not self.stop_event.is_set():
                await asyncio.sleep(0.1)

    def _handle_message(self, message: str | bytes) -> None:
        try:
            payload = GameStatePayload.from_json(message)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.last_error = f"invalid payload: {exc}"
            debug_log("PokerWebSocketBridge rejected payload: %s", exc)
            return

        if payload.event not in {"table_update", "ping"}:
            debug_log("PokerWebSocketBridge ignoring event=%s", payload.event)
            return

        if payload.event == "ping":
            return

        self.messages_received += 1
        self.last_payload = payload
        self._sequence += 1
        update = BridgeTableUpdate(
            payload=payload,
            received_at=time.monotonic(),
            sequence=self._sequence,
        )
        self._enqueue(update)

    def _enqueue(self, update: BridgeTableUpdate) -> None:
        while True:
            try:
                self.output_queue.put_nowait(update)
                return
            except queue.Full:
                try:
                    self.output_queue.get_nowait()
                except queue.Empty:
                    return
