"""JSON message schema between the userscript extractor and the v2 backend."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..constants import SCHEMA_VERSION

ALLOWED_MESSAGE_TYPES = frozenset({"hello", "ping", "table_delta"})


@dataclass(frozen=True)
class TableDeltaMessage:
    """Normalized userscript payload for one visible table-state read."""

    schema_version: int
    message_type: str
    seq: int
    ts_ms: int
    source_url: str | None = None
    pot_raw: str | None = None
    pot_parsed: float | None = None
    hero_cards: tuple[str, ...] = ()
    board_cards: tuple[str, ...] = ()
    hero_stack_raw: str | None = None
    hero_stack_parsed: float | None = None
    hero_turn: bool = False
    slot_left_raw: str = ""
    slot_centre_raw: str = ""
    slot_right_raw: str = ""
    amount_to_call_raw: str | None = None
    amount_to_call_parsed: float | None = None
    legal_actions: tuple[str, ...] = ()
    post_hand_ui: bool = False
    post_hand_labels: tuple[str, ...] = ()
    street_hint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_json(cls, payload: str | bytes) -> TableDeltaMessage:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("message must be a JSON object")

        message_type = str(data.get("message_type", data.get("event", "table_delta")))
        if message_type not in ALLOWED_MESSAGE_TYPES:
            raise ValueError(f"unsupported message_type: {message_type}")

        hero_cards = _as_str_tuple(data.get("hero_cards", data.get("hero_card_texts", ())))
        board_cards = _as_str_tuple(data.get("board_cards", data.get("board_card_texts", ())))
        legal_actions = _as_str_tuple(data.get("legal_actions", ()))
        post_hand_labels = _as_str_tuple(data.get("post_hand_labels", data.get("post_hand_texts", ())))

        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            message_type=message_type,
            seq=int(data.get("seq", data.get("sequence", 0))),
            ts_ms=int(data.get("ts_ms", data.get("ts", 0))),
            source_url=_optional_str(data.get("source_url")),
            pot_raw=_optional_str(data.get("pot_raw", data.get("pot_text"))),
            pot_parsed=_optional_float(data.get("pot_parsed", data.get("pot"))),
            hero_cards=hero_cards,
            board_cards=board_cards,
            hero_stack_raw=_optional_str(data.get("hero_stack_raw", data.get("stack_text"))),
            hero_stack_parsed=_optional_float(data.get("hero_stack_parsed", data.get("stack"))),
            hero_turn=bool(data.get("hero_turn", False)),
            slot_left_raw=str(data.get("slot_left_raw", data.get("action_slot_left", "")) or ""),
            slot_centre_raw=str(data.get("slot_centre_raw", data.get("action_slot_centre", "")) or ""),
            slot_right_raw=str(data.get("slot_right_raw", data.get("action_slot_right", "")) or ""),
            amount_to_call_raw=_optional_str(data.get("amount_to_call_raw", data.get("call_text"))),
            amount_to_call_parsed=_optional_float(data.get("amount_to_call_parsed", data.get("to_call"))),
            legal_actions=legal_actions,
            post_hand_ui=bool(data.get("post_hand_ui", False)),
            post_hand_labels=post_hand_labels,
            street_hint=_optional_str(data.get("street_hint", data.get("street"))),
            raw=data,
        )

    @property
    def is_table_delta(self) -> bool:
        return self.message_type == "table_delta"


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
