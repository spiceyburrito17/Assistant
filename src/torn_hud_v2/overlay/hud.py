"""Separate local Tk overlay for v2 recommendations."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass

from ..models.snapshot import RecommendationView, TableSnapshot


@dataclass(frozen=True)
class OverlayUpdate:
    snapshot: TableSnapshot
    recommendation: RecommendationView
    diagnostics: dict[str, str]


class HudOverlay:
    """Minimal always-on-top HUD window, independent from the browser page."""

    def __init__(self, title: str = "Torn HUD v2") -> None:
        self.title = title
        self.update_queue: queue.Queue[OverlayUpdate] = queue.Queue(maxsize=8)
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_ui, name="torn-hud-v2-overlay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def publish(self, update: OverlayUpdate) -> None:
        while True:
            try:
                self.update_queue.put_nowait(update)
                return
            except queue.Full:
                try:
                    self.update_queue.get_nowait()
                except queue.Empty:
                    return

    def _run_ui(self) -> None:
        root = tk.Tk()
        root.title(self.title)
        root.attributes("-topmost", True)
        root.geometry("420x220+40+40")
        root.configure(bg="#101820")

        title = tk.Label(root, text="Torn HUD v2", fg="#ECF0F1", bg="#101820", font=("Segoe UI", 14, "bold"))
        title.pack(anchor="w", padx=12, pady=(10, 4))

        self.action_label = tk.Label(root, text="WAIT", fg="#3498DB", bg="#101820", font=("Segoe UI", 24, "bold"))
        self.action_label.pack(anchor="w", padx=12)

        self.detail_label = tk.Label(root, text="Waiting for DOM bridge…", fg="#BDC3C7", bg="#101820", wraplength=380, justify="left")
        self.detail_label.pack(anchor="w", padx=12, pady=6)

        self.diagnostics_label = tk.Label(root, text="", fg="#95A5A6", bg="#101820", wraplength=380, justify="left")
        self.diagnostics_label.pack(anchor="w", padx=12)

        def poll() -> None:
            if self.stop_event.is_set():
                root.destroy()
                return
            while True:
                try:
                    update = self.update_queue.get_nowait()
                except queue.Empty:
                    break
                else:
                    self._render(update)
            root.after(100, poll)

        root.after(100, poll)
        root.mainloop()

    def _render(self, update: OverlayUpdate) -> None:
        rec = update.recommendation
        snap = update.snapshot
        self.action_label.config(text=rec.action.value.upper())
        self.detail_label.config(text=rec.detail)
        diag_lines = [
            f"street={snap.street.value} hero_turn={snap.hero_turn}",
            f"pot={snap.pot.parsed} to_call={snap.amount_to_call.parsed}",
            f"confidence={rec.state_confidence.value} solver={rec.solver_status.value}",
        ]
        diag_lines.extend(f"{key}={value}" for key, value in update.diagnostics.items())
        self.diagnostics_label.config(text=" | ".join(diag_lines))
