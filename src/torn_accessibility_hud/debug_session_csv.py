"""Single-file CSV debug log for comparing table state vs HUD parsing."""

from __future__ import annotations

import csv
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import GameSnapshot, Recommendation, RecommendedAction, TableParseDiagnostics

DEFAULT_SESSION_CSV_PATH = Path("debug_captures/debug_current_session.csv")

CSV_COLUMNS: tuple[str, ...] = (
    "timestamp",
    "event_type",
    "hand_id",
    "street",
    "hero_cards",
    "board_cards",
    "pot_raw",
    "pot_parsed",
    "fold_button_raw",
    "call_button_raw",
    "raise_button_raw",
    "amount_to_call_raw",
    "amount_to_call_parsed",
    "legal_actions_raw",
    "legal_actions_normalized",
    "hero_turn",
    "current_recommendation",
    "block_reason",
    "state_confidence",
    "solver_status",
)

_EVENT_PRIORITY: tuple[str, ...] = (
    "blocked",
    "decision",
    "hero_turn",
    "street_change",
    "actions_update",
)


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    text = str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _join_values(values: tuple[str, ...] | list[str]) -> str:
    if not values:
        return ""
    return "|".join(_csv_cell(item) for item in values)


class SessionDebugCSVLogger:
    """Append-only CSV logger that resets to a fresh header on startup."""

    def __init__(self, path: str | Path = DEFAULT_SESSION_CSV_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        """Overwrite any existing file and write a fresh header row."""

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

    def log_debug_state(self, **fields: Any) -> None:
        """Append one CSV-safe debug row."""

        row = {column: _csv_cell(fields.get(column)) for column in CSV_COLUMNS}
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="") as fp:
                writer = csv.DictWriter(
                    fp,
                    fieldnames=list(CSV_COLUMNS),
                    lineterminator="\n",
                    quoting=csv.QUOTE_MINIMAL,
                )
                writer.writerow(row)


class SessionDebugEventTracker:
    """Detect meaningful state transitions and emit one CSV row per event."""

    def __init__(self, logger: SessionDebugCSVLogger) -> None:
        self.logger = logger
        self.hand_id = 0
        self._last_hero_cards: tuple[str, ...] = ()
        self._last_street: str | None = None
        self._last_legal_actions: tuple[str, ...] = ()
        self._last_normalized_actions: tuple[str, ...] = ()
        self._last_recommendation: str | None = None
        self._last_block_reason: str | None = None

    def observe(
        self,
        snapshot: GameSnapshot,
        recommendation: Recommendation,
    ) -> None:
        events = self._detect_events(snapshot, recommendation)
        if not events:
            return

        row = self._build_row(snapshot, recommendation)
        ordered_events = [event for event in _EVENT_PRIORITY if event in events]
        for event_type in ordered_events:
            self.logger.log_debug_state(**row, event_type=event_type)

    def _detect_events(
        self,
        snapshot: GameSnapshot,
        recommendation: Recommendation,
    ) -> set[str]:
        events: set[str] = set()
        diag = snapshot.parse_diagnostics
        legal_actions = tuple(action.value for action in snapshot.legal_actions)
        normalized_actions = tuple(diag.legal_actions_normalized) if diag is not None else ()
        street = snapshot.street.value
        block_reason = recommendation.decision_blocked_reason or (
            diag.block_reason if diag is not None else None
        )

        if len(snapshot.hero_cards) == 2 and snapshot.hero_cards != self._last_hero_cards:
            self.hand_id += 1

        if self._last_street is not None and street != self._last_street:
            events.add("street_change")

        if legal_actions and not self._last_legal_actions:
            events.add("hero_turn")

        if normalized_actions and normalized_actions != self._last_normalized_actions:
            events.add("actions_update")

        recommendation_action = recommendation.action.value
        if (
            recommendation_action != RecommendedAction.WAIT.value
            and recommendation_action != self._last_recommendation
        ):
            events.add("decision")

        if block_reason and block_reason != self._last_block_reason:
            events.add("blocked")

        self._last_hero_cards = snapshot.hero_cards
        self._last_street = street
        self._last_legal_actions = legal_actions
        self._last_normalized_actions = normalized_actions
        self._last_recommendation = recommendation_action
        self._last_block_reason = block_reason
        return events

    def _build_row(
        self,
        snapshot: GameSnapshot,
        recommendation: Recommendation,
    ) -> dict[str, Any]:
        diag = snapshot.parse_diagnostics or TableParseDiagnostics()
        pot_parsed = diag.pot_parsed if diag.pot_parsed is not None else diag.pot_normalized
        block_reason = recommendation.decision_blocked_reason or diag.block_reason
        hero_turn = bool(snapshot.legal_actions)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "hand_id": self.hand_id,
            "street": snapshot.street.value,
            "hero_cards": _join_values(snapshot.hero_cards),
            "board_cards": _join_values(snapshot.board_cards),
            "pot_raw": diag.pot_crop_text or diag.pot_raw or "",
            "pot_parsed": pot_parsed if pot_parsed is not None else "",
            "fold_button_raw": diag.fold_button_raw or "",
            "call_button_raw": diag.call_button_raw or "",
            "raise_button_raw": diag.raise_button_raw or "",
            "amount_to_call_raw": diag.amount_to_call_raw or "",
            "amount_to_call_parsed": (
                diag.amount_to_call_parsed if diag.amount_to_call_parsed is not None else ""
            ),
            "legal_actions_raw": _join_values(diag.legal_actions_raw),
            "legal_actions_normalized": _join_values(diag.legal_actions_normalized),
            "hero_turn": hero_turn,
            "current_recommendation": recommendation.action.value,
            "block_reason": block_reason or "",
            "state_confidence": snapshot.state_confidence.value,
            "solver_status": recommendation.solver_status.value,
        }
