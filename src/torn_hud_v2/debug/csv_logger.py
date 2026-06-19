"""Session debug CSV logger for the v2 DOM-first engine."""

from __future__ import annotations

import csv
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..constants import CSV_COLUMNS, DEFAULT_SESSION_CSV_PATH
from .sanitizer import sanitize_csv_cell


class SessionCSVLogger:
    """Overwrite CSV on startup, then append one row per meaningful state change."""

    def __init__(self, path: str | Path = DEFAULT_SESSION_CSV_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Clear any existing file and write header only."""

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(
                    fp,
                    fieldnames=list(CSV_COLUMNS),
                    lineterminator="\n",
                    quoting=csv.QUOTE_MINIMAL,
                )
                writer.writeheader()

    def log_row(self, row: Mapping[str, Any]) -> None:
        sanitized = {column: sanitize_csv_cell(row.get(column)) for column in CSV_COLUMNS}
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(
                    fp,
                    fieldnames=list(CSV_COLUMNS),
                    lineterminator="\n",
                    quoting=csv.QUOTE_MINIMAL,
                )
                writer.writerow(sanitized)
