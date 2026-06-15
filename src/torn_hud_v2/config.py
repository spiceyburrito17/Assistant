"""Runtime configuration for the v2 DOM-first HUD."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_SESSION_CSV_PATH, DEFAULT_WS_HOST, DEFAULT_WS_PORT


@dataclass(frozen=True)
class HudConfig:
    ws_host: str = DEFAULT_WS_HOST
    ws_port: int = DEFAULT_WS_PORT
    session_csv_path: str = DEFAULT_SESSION_CSV_PATH
    session_csv_enabled: bool = True
    poll_interval_sec: float = 0.05

    @classmethod
    def load(cls, path: Path | None) -> HudConfig:
        if path is None or not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            ws_host=str(raw.get("ws_host", DEFAULT_WS_HOST)),
            ws_port=int(raw.get("ws_port", DEFAULT_WS_PORT)),
            session_csv_path=str(raw.get("session_csv_path", DEFAULT_SESSION_CSV_PATH)),
            session_csv_enabled=bool(raw.get("session_csv_enabled", True)),
            poll_interval_sec=float(raw.get("poll_interval_sec", 0.05)),
        )
