"""Localhost WebSocket receiver for userscript table deltas."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any, Callable

from ..constants import DEFAULT_WS_HOST, DEFAULT_WS_PORT
from ..models.messages import TableDeltaMessage

MessageHandler = Callable[[TableDeltaMessage], None]


class WebSocketReceiver:
    """Background asyncio WebSocket server that forwards validated messages."""

    def __init__(
        self,
        on_message: MessageHandler,
        *,
        host: str = DEFAULT_WS_HOST,
        port: int = DEFAULT_WS_PORT,
    ) -> None:
        self.on_message = on_message
        self.host = host
        self.port = port
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last_error: str | None = None
        self.messages_received = 0
        self.client_count = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="torn-hud-v2-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"

    async def _serve(self) -> None:
        import websockets
        from websockets.server import WebSocketServerProtocol

        self._loop = asyncio.get_running_loop()

        async def handler(websocket: WebSocketServerProtocol) -> None:
            self.client_count += 1
            try:
                async for message in websocket:
                    self._handle_message(message)
            finally:
                self.client_count -= 1

        async with websockets.serve(handler, self.host, self.port):
            while not self.stop_event.is_set():
                await asyncio.sleep(0.1)

    def _handle_message(self, message: str | bytes) -> None:
        try:
            payload = TableDeltaMessage.from_json(message)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.last_error = f"invalid payload: {exc}"
            return
        if payload.message_type in {"ping", "hello"}:
            return
        self.messages_received += 1
        self.on_message(payload)


class MessageQueueBridge:
    """Optional queue adapter when the app loop drains messages manually."""

    def __init__(self, output_queue: queue.Queue[TableDeltaMessage], maxsize: int = 32) -> None:
        self.output_queue = output_queue
        self.maxsize = maxsize

    def __call__(self, message: TableDeltaMessage) -> None:
        while True:
            try:
                self.output_queue.put_nowait(message)
                return
            except queue.Full:
                try:
                    self.output_queue.get_nowait()
                except queue.Empty:
                    return
