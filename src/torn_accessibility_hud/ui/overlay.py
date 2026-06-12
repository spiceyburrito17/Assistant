"""Transparent Tkinter overlay that never performs heavy work."""

from __future__ import annotations

import queue
import tkinter as tk

from ..config import OverlayConfig
from ..models import OverlayState, RecommendationLevel


class TkOverlay:
    """Small always-on-top overlay updated from a latest-only queue."""

    def __init__(self, config: OverlayConfig | None = None) -> None:
        self.config = config or OverlayConfig()
        self.state_queue: queue.Queue[OverlayState] = queue.Queue(maxsize=2)
        self.root: tk.Tk | None = None
        self.title_var: tk.StringVar | None = None
        self.detail_var: tk.StringVar | None = None
        self.cards_var: tk.StringVar | None = None
        self.stats_var: tk.StringVar | None = None
        self.log_var: tk.StringVar | None = None
        self.title_label: tk.Label | None = None
        self._closed = False

    def publish(self, state: OverlayState) -> None:
        while True:
            try:
                self.state_queue.put_nowait(state)
                return
            except queue.Full:
                try:
                    self.state_queue.get_nowait()
                except queue.Empty:
                    return

    def start(self) -> None:
        self.root = tk.Tk()
        self.root.title(self.config.title)
        self.root.geometry(f"{self.config.width}x{self.config.height}+{self.config.x}+{self.config.y}")
        self.root.configure(bg=self.config.background_hex)
        self.root.attributes("-alpha", self.config.alpha)
        if self.config.always_on_top:
            self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.title_var = tk.StringVar(value="WAIT")
        self.detail_var = tk.StringVar(value="Waiting for stable OCR.")
        self.cards_var = tk.StringVar(value="Cards: --")
        self.stats_var = tk.StringVar(value="Opponents: --")
        self.log_var = tk.StringVar(value="")

        self.title_label = tk.Label(
            self.root,
            textvariable=self.title_var,
            font=("Helvetica", 30, "bold"),
            bg=self.config.background_hex,
            fg="#3498DB",
        )
        self.title_label.pack(fill="x", padx=10, pady=(10, 0))
        detail = tk.Label(
            self.root,
            textvariable=self.detail_var,
            font=("Helvetica", 13),
            wraplength=self.config.width - 24,
            justify="center",
            bg=self.config.background_hex,
            fg=self.config.text_hex,
        )
        detail.pack(fill="x", padx=10, pady=(4, 8))
        cards = tk.Label(
            self.root,
            textvariable=self.cards_var,
            font=("Helvetica", 12, "bold"),
            bg=self.config.background_hex,
            fg=self.config.text_hex,
            justify="left",
        )
        cards.pack(fill="x", padx=12)
        stats = tk.Label(
            self.root,
            textvariable=self.stats_var,
            font=("Helvetica", 10),
            bg=self.config.background_hex,
            fg=self.config.text_hex,
            justify="left",
        )
        stats.pack(fill="x", padx=12, pady=(6, 0))
        logs = tk.Label(
            self.root,
            textvariable=self.log_var,
            font=("Helvetica", 9),
            bg=self.config.background_hex,
            fg="#BDC3C7",
            justify="left",
            anchor="nw",
        )
        logs.pack(fill="both", expand=True, padx=12, pady=(6, 10))

        self.root.after(self.config.poll_interval_ms, self._poll)
        self.root.mainloop()

    def close(self) -> None:
        self._closed = True
        if self.root is not None:
            self.root.destroy()

    def _poll(self) -> None:
        if self._closed or self.root is None:
            return
        latest: OverlayState | None = None
        while True:
            try:
                latest = self.state_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._render(latest)
        self.root.after(self.config.poll_interval_ms, self._poll)

    def _render(self, state: OverlayState) -> None:
        assert self.root is not None
        assert self.title_var is not None
        assert self.detail_var is not None
        assert self.cards_var is not None
        assert self.stats_var is not None
        assert self.log_var is not None
        assert self.title_label is not None

        recommendation = state.recommendation
        self.title_var.set(recommendation.title)
        self.detail_var.set(recommendation.detail)
        title_color = recommendation.color_hex
        if recommendation.level is RecommendationLevel.UNKNOWN:
            title_color = "#95A5A6"
        self.title_label.configure(fg=title_color)

        snapshot = state.snapshot
        hero = " ".join(snapshot.hero_cards) if snapshot.hero_cards else "--"
        board = " ".join(snapshot.board_cards) if snapshot.board_cards else "--"
        self.cards_var.set(
            f"Hero: {hero}    Board: {board}\nPot: {snapshot.pot_size:,.0f}    To call: {snapshot.to_call:,.0f}"
        )
        if snapshot.opponent_stats:
            rendered = []
            for stat in snapshot.opponent_stats[:4]:
                rendered.append(
                    f"{stat.player_name}: VPIP {stat.vpip:.0%} PFR {stat.pfr:.0%} "
                    f"last {stat.last_action} range {','.join(stat.top_range_classes[:3])}"
                )
            self.stats_var.set("\n".join(rendered))
        else:
            self.stats_var.set("Opponents: waiting for readable actions")
        self.log_var.set("\n".join(state.latest_lines[-4:]))
