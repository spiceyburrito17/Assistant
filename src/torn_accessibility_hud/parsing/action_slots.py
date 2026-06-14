"""Parse Torn poker action bar from three fixed left/centre/right OCR slots."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ActionSlotOCRResult, RecommendedAction, TableOCRResult
from .action_ui import is_post_hand_ui
from .action_validator import validate_action_inputs
from .amounts import call_amount_present, raise_to_pattern_present
from .legal_actions import LEGAL_ACTION_LABELS, legal_action_to_recommended
from .slot_amounts import normalize_slot_action_text_for_amounts, parse_amount_to_call_from_slot_text

ACTION_SLOT_NAMES: tuple[str, ...] = (
    "action_slot_left",
    "action_slot_centre",
    "action_slot_right",
)

_CALL_ANY_RE = re.compile(r"\bcall\s+any\b", re.IGNORECASE)
_CHECK_RE = re.compile(r"\bcheck\b", re.IGNORECASE)
_CALL_RE = re.compile(r"\bcall\b", re.IGNORECASE)
_FOLD_RE = re.compile(r"\bfold\b", re.IGNORECASE)
_BET_RE = re.compile(r"\bbet\b", re.IGNORECASE)
_RAISE_RE = re.compile(r"\braise\b", re.IGNORECASE)
_RAISE_TO_AMOUNT_RE = re.compile(
    r"\braise\s+to\b[^0-9$£€]*(?:[$£€])?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SlotClassification:
    slot_name: str
    raw_text: str
    label: str | None = None
    ambiguous: bool = False
    post_hand: bool = False
    pre_action_toggle: bool = False


@dataclass(frozen=True)
class ParsedActionBar:
    slot_left_raw: str = ""
    slot_centre_raw: str = ""
    slot_right_raw: str = ""
    slot_left_coords: str | None = None
    slot_centre_coords: str | None = None
    slot_right_coords: str | None = None
    post_hand_ui: bool = False
    legal_actions: tuple[RecommendedAction, ...] = ()
    legal_actions_normalized: tuple[str, ...] = ()
    legal_actions_raw: tuple[str, ...] = ()
    amount_to_call_raw: str | None = None
    amount_to_call_parsed: float | None = None
    actions_ambiguous: bool = False
    block_reason: str | None = None


def classify_slot_text(slot_name: str, text: str) -> SlotClassification:
    stripped = normalize_slot_action_text_for_amounts(text.strip())
    if not stripped:
        return SlotClassification(slot_name=slot_name, raw_text=text.strip())

    if is_post_hand_ui(stripped):
        return SlotClassification(slot_name=slot_name, raw_text=stripped, post_hand=True)

    if _FOLD_RE.search(stripped):
        return SlotClassification(slot_name=slot_name, raw_text=stripped, label="fold")

    if _CALL_ANY_RE.search(stripped):
        return SlotClassification(
            slot_name=slot_name,
            raw_text=stripped,
            label="check",
            pre_action_toggle=True,
        )

    if raise_to_pattern_present(stripped) or _RAISE_TO_AMOUNT_RE.search(stripped):
        return SlotClassification(slot_name=slot_name, raw_text=stripped, label="raise")

    if _BET_RE.search(stripped) and not _RAISE_RE.search(stripped):
        return SlotClassification(slot_name=slot_name, raw_text=stripped, label="bet")

    if _CALL_RE.search(stripped):
        if _CALL_ANY_RE.search(stripped):
            parsed, _status = parse_amount_to_call_from_slot_text(stripped)
            if parsed is None or parsed == 0:
                return SlotClassification(
                    slot_name=slot_name,
                    raw_text=stripped,
                    label="check",
                    pre_action_toggle=True,
                )
        return SlotClassification(slot_name=slot_name, raw_text=stripped, label="call")

    if _CHECK_RE.search(stripped) and not call_amount_present(stripped):
        return SlotClassification(slot_name=slot_name, raw_text=stripped, label="check")

    return SlotClassification(slot_name=slot_name, raw_text=stripped, ambiguous=True)


def _slot_raw_map(table_ocr: TableOCRResult) -> dict[str, ActionSlotOCRResult]:
    return {slot.slot_name: slot for slot in table_ocr.slots}


def _slot_display_raw(slot: ActionSlotOCRResult | None) -> str:
    if slot is None:
        return ""
    return slot.ocr_scan_raw or ""


def parse_action_bar(table_ocr: TableOCRResult) -> ParsedActionBar:
    slot_map = _slot_raw_map(table_ocr)
    left = slot_map.get("action_slot_left")
    centre = slot_map.get("action_slot_centre")
    right = slot_map.get("action_slot_right")

    left_raw = _slot_display_raw(left)
    centre_raw = _slot_display_raw(centre)
    right_raw = _slot_display_raw(right)

    classifications = [
        classify_slot_text(name, _slot_display_raw(slot_map.get(name)))
        for name in ACTION_SLOT_NAMES
    ]

    if any(item.post_hand for item in classifications):
        return ParsedActionBar(
            slot_left_raw=left_raw,
            slot_centre_raw=centre_raw,
            slot_right_raw=right_raw,
            slot_left_coords=left.region_coords if left else None,
            slot_centre_coords=centre.region_coords if centre else None,
            slot_right_coords=right.region_coords if right else None,
            post_hand_ui=True,
            block_reason="post_hand",
        )

    normalized: list[str] = []
    raw_entries: list[str] = []
    ambiguous = False
    call_slot_raw: str | None = None
    raise_slot_raw: str | None = None

    for item in classifications:
        if not item.raw_text:
            continue
        raw_entries.append(f"{item.slot_name}={item.raw_text!r}")
        if item.ambiguous:
            ambiguous = True
            continue
        if item.label is None:
            continue
        normalized.append(item.label)
        if item.label == "call":
            call_slot_raw = item.raw_text
        if item.label in {"raise", "bet"}:
            raise_slot_raw = item.raw_text

    if call_slot_raw is None:
        for item in classifications:
            if item.label == "check" and item.raw_text:
                call_slot_raw = item.raw_text
                break

    validated = validate_action_inputs(
        normalized_labels=tuple(normalized),
        raw_entries=tuple(raw_entries),
        actions_ambiguous=ambiguous,
        call_slot_raw=call_slot_raw,
        raise_slot_raw=raise_slot_raw,
        action_regions_scanned=table_ocr.action_regions_scanned,
    )

    return ParsedActionBar(
        slot_left_raw=left_raw,
        slot_centre_raw=centre_raw,
        slot_right_raw=right_raw,
        slot_left_coords=left.region_coords if left else None,
        slot_centre_coords=centre.region_coords if centre else None,
        slot_right_coords=right.region_coords if right else None,
        post_hand_ui=False,
        legal_actions=validated.legal_actions,
        legal_actions_normalized=validated.normalized_labels,
        legal_actions_raw=validated.raw_entries,
        amount_to_call_raw=validated.amount_to_call.raw_text,
        amount_to_call_parsed=validated.amount_to_call.parsed,
        actions_ambiguous=validated.actions_ambiguous,
        block_reason=validated.block_reason,
    )


def merge_slot_labels(labels: tuple[str, ...]) -> tuple[RecommendedAction, ...]:
    merged: list[RecommendedAction] = []
    seen: set[RecommendedAction] = set()
    for label in labels:
        if label not in LEGAL_ACTION_LABELS:
            continue
        recommended = legal_action_to_recommended(label)
        if recommended in seen:
            continue
        merged.append(recommended)
        seen.add(recommended)
    return tuple(merged)
