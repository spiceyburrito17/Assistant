"""Transparent Tkinter overlay that never performs heavy work."""

from __future__ import annotations

import queue
import tkinter as tk

from ..config import OverlayConfig
from ..models import DecisionConfidence, OverlayState, RecommendedAction


class TkOverlay:
    """Small always-on-top overlay updated from a latest-only queue."""

    def __init__(self, config: OverlayConfig | None = None) -> None:
        self.config = config or OverlayConfig()
        self.state_queue: queue.Queue[OverlayState] = queue.Queue(maxsize=2)
        self.root: tk.Tk | None = None
        self.title_var: tk.StringVar | None = None
        self.detail_var: tk.StringVar | None = None
        self.summary_var: tk.StringVar | None = None
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
        self.summary_var = tk.StringVar(value="")
        self.stats_var = tk.StringVar(value="Opponents: --")
        self.log_var = tk.StringVar(value="")

        self.title_label = tk.Label(
            self.root,
            textvariable=self.title_var,
            font=("Helvetica", 28, "bold"),
            bg=self.config.background_hex,
            fg="#3498DB",
        )
        self.title_label.pack(fill="x", padx=10, pady=(10, 0))
        detail = tk.Label(
            self.root,
            textvariable=self.detail_var,
            font=("Helvetica", 11),
            wraplength=self.config.width - 24,
            justify="left",
            bg=self.config.background_hex,
            fg=self.config.text_hex,
        )
        detail.pack(fill="x", padx=12, pady=(4, 6))
        summary = tk.Label(
            self.root,
            textvariable=self.summary_var,
            font=("Consolas", 11),
            bg=self.config.background_hex,
            fg=self.config.text_hex,
            justify="left",
            anchor="nw",
        )
        summary.pack(fill="x", padx=12)
        stats = tk.Label(
            self.root,
            textvariable=self.stats_var,
            font=("Helvetica", 9),
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
        assert self.summary_var is not None
        assert self.stats_var is not None
        assert self.log_var is not None
        assert self.title_label is not None

        recommendation = state.recommendation
        snapshot = state.snapshot
        self.title_var.set(recommendation.title)
        self.detail_var.set(recommendation.detail)
        self.title_label.configure(fg=recommendation.color_hex)

        hero = " ".join(snapshot.hero_cards) if snapshot.hero_cards else "--"
        board = " ".join(snapshot.board_cards) if snapshot.board_cards else "--"
        pot_display = f"{snapshot.pot_size:,.0f}" if snapshot.pot_size > 0 else "--"
        equity = self._format_percent(recommendation.equity)
        required = self._format_percent(recommendation.required_equity)
        edge = self._format_edge(recommendation.edge)
        action = recommendation.action.value.upper()
        confidence = recommendation.confidence.value.upper()
        summary_lines = [
            f"Hero:       {hero}",
            f"Board:      {board}",
            f"Pot:        {pot_display}",
            f"To call:    {snapshot.to_call:,.0f}",
            f"Equity:     {equity}",
            f"Required:   {required}",
            f"Edge:       {edge}",
            f"Action:     {action}",
            f"Confidence: {confidence}",
        ]
        if recommendation.action is RecommendedAction.RAISE and recommendation.raise_sizing is not None:
            sizing = recommendation.raise_sizing
            summary_lines.extend(
                [
                    f"Min raise:  {sizing.min_raise:,.0f}",
                    f"Half pot:   {sizing.half_pot:,.0f}",
                    f"Two-thirds: {sizing.two_thirds_pot:,.0f}",
                    f"Pot:        {sizing.pot:,.0f}",
                ]
            )
        if recommendation.confidence is DecisionConfidence.LOW and recommendation.confidence_notes:
            summary_lines.append(f"Notes:      {', '.join(recommendation.confidence_notes)}")
        parse_diag = recommendation.parse_diagnostics or state.snapshot.parse_diagnostics
        if parse_diag is not None:
            crop_text = parse_diag.pot_crop_text or parse_diag.pot_raw or "--"
            summary_lines.append(f"pot_crop_text={crop_text}")
            summary_lines.append(
                f"pot_anchor_match={parse_diag.pot_anchor_match or '--'}"
            )
            summary_lines.append(
                "pot_anchor_confidence="
                f"{parse_diag.pot_anchor_confidence if parse_diag.pot_anchor_confidence is not None else '--'}"
            )
            summary_lines.append(
                f"pot_digits_start={parse_diag.pot_digits_start if parse_diag.pot_digits_start is not None else '--'}"
            )
            summary_lines.append(f"pot_candidate={parse_diag.pot_candidate or '--'}")
            live_pot = (
                f"{parse_diag.pot_parsed:,.0f}"
                if parse_diag.pot_parsed is not None
                else "--"
            )
            summary_lines.append(f"pot_live_parse={live_pot}")
            parsed_pot = (
                f"{parse_diag.pot_normalized:,.0f}"
                if parse_diag.pot_normalized is not None
                else "--"
            )
            summary_lines.append(f"pot_trusted={parsed_pot}")
            if parse_diag.pot_rejected_reason:
                summary_lines.append(f"pot_rejected_reason={parse_diag.pot_rejected_reason}")
            summary_lines.append(
                f"legal_actions_raw=[{', '.join(parse_diag.legal_actions_raw) or '--'}]"
            )
            summary_lines.append(
                "legal_actions_normalized=["
                f"{', '.join(parse_diag.legal_actions_normalized) or '--'}]"
            )
            summary_lines.append(f"amount_to_call_raw={parse_diag.amount_to_call_raw or '--'}")
            parsed_to_call = (
                f"{parse_diag.amount_to_call_parsed:,.0f}"
                if parse_diag.amount_to_call_parsed is not None
                else "--"
            )
            summary_lines.append(f"amount_to_call_parsed={parsed_to_call}")
            summary_lines.append(f"slot_left_raw={parse_diag.slot_left_raw or '--'}")
            summary_lines.append(f"slot_centre_raw={parse_diag.slot_centre_raw or '--'}")
            summary_lines.append(f"slot_right_raw={parse_diag.slot_right_raw or '--'}")
            if parse_diag.button_overlap_suspected:
                summary_lines.append(f"button_overlap_suspected={parse_diag.button_overlap_suspected}")
            if parse_diag.block_reason:
                summary_lines.append(f"block_reason={parse_diag.block_reason}")
        debug_lines = [
            f"state_confidence={recommendation.state_confidence.value}",
            f"legal_actions=[{', '.join(action.value for action in recommendation.legal_actions) or '--'}]",
            f"solver_status={recommendation.solver_status.value}",
        ]
        if recommendation.decision_blocked_reason:
            debug_lines.append(f"decision_blocked_reason={recommendation.decision_blocked_reason}")
        summary_lines.extend(debug_lines)
        self.summary_var.set("\n".join(summary_lines))

        if snapshot.opponent_stats:
            rendered = []
            for stat in snapshot.opponent_stats[:3]:
                rendered.append(
                    f"{stat.player_name}: VPIP {stat.vpip:.0%} PFR {stat.pfr:.0%} "
                    f"last {stat.last_action}"
                )
            self.stats_var.set("\n".join(rendered))
        else:
            self.stats_var.set("Opponents: waiting for readable actions")
        self.log_var.set("\n".join(state.latest_lines[-3:]))

    @staticmethod
    def _format_percent(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:.1%}"

    @staticmethod
    def _format_edge(value: float | None) -> str:
        if value is None:
            return "--"
        return f"{value:+.1%}"
