"""Robust parsing of noisy Torn poker OCR text logs."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from ..config import ParserConfig
from ..models import ActionType, OCRLine, ParsedEvent, Street
from .cards import normalize_ocr_text, parse_cards, validate_cards

_AMOUNT_RE = re.compile(r"(?<![a-z])(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)")
_PLAYER_ACTION_RE = re.compile(
    r"^(?P<player>.+?)\s+(?P<action>folds?|checks?|calls?|bets?|raises(?:\s+to)?|"
    r"raised(?:\s+to)?|called|checked|folded|all[- ]in|shoves|posts\s+(?:small|big)?\s*blind)"
    r"(?:\s+(?P<amount>[$£€]?\s*[0-9][0-9,]*(?:\.[0-9]+)?))?",
    re.IGNORECASE,
)
_POT_RE = re.compile(r"\bpot\b[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
_TO_CALL_RE = re.compile(r"\b(?:to\s+call|call)\b[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)


class ActionLogParser:
    """Convert OCR lines into validated poker events.

    The parser is intentionally conservative: malformed cards, duplicate cards,
    unreasonable chip amounts, or low-confidence OCR lines are ignored.
    """

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig()
        self.action_aliases = self._load_action_aliases(self.config.action_patterns_path)

    def parse_lines(self, lines: tuple[OCRLine, ...]) -> tuple[ParsedEvent, ...]:
        events: list[ParsedEvent] = []
        for line in lines:
            event = self.parse_line(line)
            if event is not None:
                events.append(event)
        return tuple(events)

    def parse_line(self, line: OCRLine) -> ParsedEvent | None:
        if line.confidence < self.config.min_line_confidence:
            return None
        text = normalize_ocr_text(line.text)
        if len(text) < 3:
            return None

        hero = self._parse_hero_cards(text, line.confidence)
        if hero is not None:
            return hero

        board = self._parse_board(text, line.confidence)
        if board is not None:
            return board

        pot = self._parse_pot(text, line.confidence)
        if pot is not None:
            return pot

        action = self._parse_player_action(text, line.confidence)
        if action is not None:
            return action
        return None

    def _parse_hero_cards(self, text: str, confidence: float) -> ParsedEvent | None:
        lowered = text.lower()
        if not any(token in lowered for token in ("you were dealt", "your hand", "hole cards", "dealt to you")):
            return None
        cards = parse_cards(text)
        if not validate_cards(cards, max_cards=2) or len(cards) != 2:
            return None
        return ParsedEvent(
            action=ActionType.DEALT_HERO,
            raw_text=text,
            cards=cards,
            street=Street.PREFLOP,
            confidence=confidence,
        )

    def _parse_board(self, text: str, confidence: float) -> ParsedEvent | None:
        lowered = text.lower()
        street: Street | None = None
        expected_min = 0
        expected_max = 5
        if "flop" in lowered:
            street = Street.FLOP
            expected_min, expected_max = 3, 3
        elif "turn" in lowered:
            street = Street.TURN
            expected_min, expected_max = 1, 4
        elif "river" in lowered:
            street = Street.RIVER
            expected_min, expected_max = 1, 5
        elif "board" in lowered:
            street = Street.FLOP
            expected_min, expected_max = 3, 5
        if street is None:
            return None
        cards = parse_cards(text)
        if not validate_cards(cards, max_cards=expected_max) or len(cards) < expected_min:
            return None
        return ParsedEvent(
            action=ActionType.BOARD,
            raw_text=text,
            cards=cards,
            street=street,
            confidence=confidence,
        )

    def _parse_pot(self, text: str, confidence: float) -> ParsedEvent | None:
        pot_match = _POT_RE.search(text)
        to_call_match = _TO_CALL_RE.search(text)
        if pot_match is None and to_call_match is None:
            return None
        amount = self._safe_amount((pot_match or to_call_match).group(1))
        if amount is None:
            return None
        action = ActionType.POT
        raw_text = text
        if to_call_match is not None and pot_match is None:
            raw_text = f"to_call {text}"
        return ParsedEvent(action=action, raw_text=raw_text, amount=amount, confidence=confidence)

    def _parse_player_action(self, text: str, confidence: float) -> ParsedEvent | None:
        match = _PLAYER_ACTION_RE.match(text)
        if match is None:
            return None
        player_name = self._sanitize_player_name(match.group("player"))
        if player_name is None:
            return None
        raw_action = match.group("action").lower().replace("-", " ")
        action = self._normalize_action(raw_action)
        amount = self._safe_amount(match.group("amount")) if match.group("amount") else None
        if action in {ActionType.CALL, ActionType.BET, ActionType.RAISE, ActionType.ALL_IN, ActionType.POST_BLIND}:
            if amount is None and action is not ActionType.ALL_IN:
                return None
        return ParsedEvent(
            action=action,
            raw_text=text,
            player_name=player_name,
            amount=amount,
            confidence=confidence,
        )

    def _safe_amount(self, raw: str | None) -> float | None:
        if not raw:
            return None
        match = _AMOUNT_RE.search(raw)
        if match is None:
            return None
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            return None
        if value < 0 or value > self.config.max_reasonable_amount:
            return None
        return value

    def _normalize_action(self, raw_action: str) -> ActionType:
        compact = " ".join(raw_action.split())
        for action_name, aliases in self.action_aliases.items():
            if any(alias in compact for alias in aliases):
                return ActionType(action_name)
        return ActionType.UNKNOWN

    @staticmethod
    def _sanitize_player_name(raw_name: str) -> str | None:
        name = re.sub(r"^[>\-\s]+", "", raw_name).strip(" :")
        name = re.sub(r"\s+", " ", name)
        if len(name) < 2 or len(name) > 32:
            return None
        if sum(ch.isalnum() for ch in name) < 2:
            return None
        return name

    @staticmethod
    def _load_action_aliases(path: str | None) -> dict[str, list[str]]:
        if path:
            with Path(path).expanduser().open("r", encoding="utf-8") as fp:
                return json.load(fp)
        with resources.files("torn_accessibility_hud.data").joinpath("action_patterns.json").open(
            "r", encoding="utf-8"
        ) as fp:
            return json.load(fp)
