"""Shared immutable models used across capture, OCR, tracking, and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class ActionType(str, Enum):
    """Normalized poker actions parsed from noisy OCR text."""

    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"
    POST_BLIND = "post_blind"
    DEALT_HERO = "dealt_hero"
    BOARD = "board"
    POT = "pot"
    UNKNOWN = "unknown"


class Street(str, Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"


class RecommendationLevel(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    DANGER = "danger"
    WAIT = "wait"
    UNKNOWN = "unknown"


class RecommendedAction(str, Enum):
    FOLD = "fold"
    CALL = "call"
    CHECK = "check"
    RAISE = "raise"
    WAIT = "wait"


class DecisionConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class TableStateConfidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class SolverStatus(str, Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    INSUFFICIENT_STATE = "insufficient_state"


@dataclass(frozen=True)
class ScreenRegion:
    """A rectangular screen region in physical pixels."""

    left: int
    top: int
    width: int
    height: int

    def to_mss(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class OCRLine:
    """One OCR text line and its confidence metadata."""

    text: str
    confidence: float
    bbox: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class PotOCRResult:
    raw_text: str
    parsed_amount: float | None
    ocr_confidence: float
    allowlist: str
    pot_candidate: str | None = None
    parse_status: str = ""


@dataclass(frozen=True)
class ButtonOCRResult:
    region_name: str
    raw_text: str
    normalized_label: str | None
    confidence: float
    ambiguous: bool
    expected_label: str | None = None
    detected_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableOCRResult:
    pot: PotOCRResult | None = None
    buttons: tuple[ButtonOCRResult, ...] = ()
    pot_region_scanned: bool = False
    action_regions_scanned: bool = False


@dataclass(frozen=True)
class TableParseDiagnostics:
    pot_raw: str | None = None
    pot_candidate: str | None = None
    pot_parsed: float | None = None
    pot_normalized: float | None = None
    pot_rejected_reason: str | None = None
    legal_actions_raw: tuple[str, ...] = ()
    legal_actions_normalized: tuple[str, ...] = ()
    actions_ambiguous: bool = False
    block_reason: str | None = None


@dataclass(frozen=True)
class OCRBatch:
    """Stable OCR output for a captured frame."""

    lines: tuple[OCRLine, ...]
    frame_id: int
    captured_at: float
    hero_region_folded: bool = False
    hero_cards_scanned: bool = False
    board_cards_scanned: bool = False
    table_ocr: TableOCRResult | None = None


@dataclass(frozen=True)
class ParsedEvent:
    """A validated event extracted from OCR text."""

    action: ActionType
    raw_text: str
    player_name: str | None = None
    amount: float | None = None
    cards: tuple[str, ...] = ()
    street: Street | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class PlayerStats:
    """Public stats shown by the overlay for one opponent."""

    player_name: str
    hands_seen: int
    vpip: float
    pfr: float
    last_action: str
    top_range_classes: tuple[str, ...]


@dataclass(frozen=True)
class GameSnapshot:
    """Current table state consumed by the equity worker."""

    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()
    pot_size: float = 0.0
    to_call: float = 0.0
    street: Street = Street.PREFLOP
    active_opponents: tuple[str, ...] = ()
    opponent_stats: tuple[PlayerStats, ...] = ()
    legal_actions: tuple[RecommendedAction, ...] = ()
    state_confidence: TableStateConfidence = TableStateConfidence.LOW
    actions_ambiguous: bool = False
    parse_diagnostics: TableParseDiagnostics | None = None
    generation: int = 0

    @property
    def has_minimum_equity_inputs(self) -> bool:
        return len(self.hero_cards) == 2 and len(self.board_cards) <= 5

    @property
    def trusted_pot_size(self) -> float | None:
        return self.pot_size if self.pot_size > 0 else None

    @property
    def trusted_to_call(self) -> float | None:
        return self.to_call


@dataclass(frozen=True)
class EquityResult:
    """Monte Carlo equity result returned by the background worker."""

    hero_equity: float | None
    tie_rate: float
    simulations: int
    generation: int
    elapsed_ms: float
    warning: str | None = None


@dataclass(frozen=True)
class RaiseSizing:
    """Suggested total wager sizes for a raise/bet line."""

    min_raise: float
    half_pot: float
    two_thirds_pot: float
    pot: float


@dataclass(frozen=True)
class Recommendation:
    """Color-coded decision output for the overlay."""

    level: RecommendationLevel
    title: str
    detail: str
    color_hex: str
    action: RecommendedAction = RecommendedAction.WAIT
    confidence: DecisionConfidence = DecisionConfidence.LOW
    confidence_notes: tuple[str, ...] = ()
    equity: float | None = None
    required_equity: float | None = None
    edge: float | None = None
    raise_sizing: RaiseSizing | None = None
    state_confidence: TableStateConfidence = TableStateConfidence.LOW
    legal_actions: tuple[RecommendedAction, ...] = ()
    solver_status: SolverStatus = SolverStatus.SKIPPED
    decision_blocked_reason: str | None = None
    parse_diagnostics: TableParseDiagnostics | None = None

    @property
    def pot_odds(self) -> float | None:
        """Backward-compatible alias for required equity."""

        return self.required_equity


@dataclass(frozen=True)
class OverlayState:
    """Everything the Tk overlay needs to render one refresh."""

    snapshot: GameSnapshot
    recommendation: Recommendation
    latest_lines: tuple[str, ...] = ()
    equity_result: EquityResult | None = None
    diagnostics: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EquityRequest:
    """A queued equity calculation request."""

    snapshot: GameSnapshot
    opponent_range_weights: Mapping[str, Mapping[str, float]]
    simulations: int
    timeout_ms: int


LineSequence = Sequence[OCRLine]
