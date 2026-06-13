"""Strict normalization of visible hero action button OCR."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..models import RecommendedAction

LEGAL_ACTION_LABELS: tuple[str, ...] = ("fold", "check", "call", "bet", "raise")
_AMBIGUITY_MARGIN = 0.08
_MIN_MATCH_SCORE = 0.58
_CHECK_BIAS_TOKENS = ("ch", "ck", "hec", "che")
_CALL_BIAS_TOKENS = ("ll", "al", "cal")

# Torn reuses physical button areas: left slot may show Call/Raise/Check; the wide
# center box often contains "Check" and "Fold" together.
REGION_SLOT_LABELS: dict[str, tuple[str, ...]] = {
    "fold_button_region": ("fold", "check"),
    "check_button_region": ("check", "fold"),
    "call_button_region": ("call", "check", "raise", "bet"),
    "raise_button_region": ("raise", "call", "bet", "check"),
    "bet_button_region": ("bet", "raise", "call"),
}


@dataclass(frozen=True)
class NormalizedLegalAction:
    label: str
    confidence: float
    raw_text: str
    ambiguous: bool = False


def _clean_action_text(text: str) -> str:
    lowered = text.strip().lower()
    lowered = re.sub(r"[^a-z\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _score_label(cleaned: str, label: str) -> float:
    if not cleaned:
        return 0.0
    if cleaned == label:
        return 1.0
    if cleaned.startswith(label):
        return 0.95
    if label in cleaned.split():
        return 0.9
    if label in cleaned:
        return 0.85
    ratio = SequenceMatcher(None, cleaned, label).ratio()
    if label == "check" and any(token in cleaned for token in _CHECK_BIAS_TOKENS):
        ratio = max(ratio, 0.72)
    if label == "call" and any(token in cleaned for token in _CALL_BIAS_TOKENS):
        ratio = max(ratio, 0.68)
    return ratio


def _label_clearly_present(cleaned: str, label: str) -> bool:
    if label in cleaned.split():
        return True
    if label in {"check", "call", "fold", "raise", "bet"} and label in cleaned:
        return _score_label(cleaned, label) >= _MIN_MATCH_SCORE
    return False


def normalize_action_text(text: str, ocr_confidence: float = 1.0) -> NormalizedLegalAction | None:
    """Map OCR text to exactly one of fold/check/call/bet/raise."""

    cleaned = _clean_action_text(text)
    if not cleaned:
        return None
    scores = {label: _score_label(cleaned, label) for label in LEGAL_ACTION_LABELS}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_label, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    ambiguous = second_score >= best_score - _AMBIGUITY_MARGIN and second_score >= _MIN_MATCH_SCORE
    if best_score < _MIN_MATCH_SCORE:
        return None
    if ambiguous:
        if {best_label, ranked[1][0]} == {"check", "call"}:
            if scores["check"] >= scores["call"]:
                best_label = "check"
                ambiguous = scores["call"] >= scores["check"] - 0.03
            else:
                best_label = "call"
                ambiguous = scores["check"] >= scores["call"] - 0.03
        else:
            ambiguous = True
    confidence = max(0.0, min(1.0, best_score * max(ocr_confidence, 0.1)))
    return NormalizedLegalAction(
        label=best_label,
        confidence=confidence,
        raw_text=text.strip(),
        ambiguous=ambiguous,
    )


def extract_actions_from_region_text(
    text: str,
    ocr_confidence: float = 1.0,
) -> tuple[NormalizedLegalAction, ...]:
    """Extract one or more action labels from a possibly wide/shared button crop."""

    cleaned = _clean_action_text(text)
    if not cleaned:
        return ()

    present = [
        label
        for label in LEGAL_ACTION_LABELS
        if _label_clearly_present(cleaned, label) and _score_label(cleaned, label) >= _MIN_MATCH_SCORE
    ]
    if len(present) >= 2:
        if "check" in present and "call" in present:
            if _score_label(cleaned, "check") >= _score_label(cleaned, "call"):
                present = [label for label in present if label != "call"]
            else:
                present = [label for label in present if label != "check"]
        results: list[NormalizedLegalAction] = []
        for label in LEGAL_ACTION_LABELS:
            if label not in present:
                continue
            score = _score_label(cleaned, label)
            results.append(
                NormalizedLegalAction(
                    label=label,
                    confidence=max(0.0, min(1.0, score * max(ocr_confidence, 0.1))),
                    raw_text=text.strip(),
                    ambiguous=False,
                )
            )
        return tuple(results)

    single = normalize_action_text(text, ocr_confidence=ocr_confidence)
    if single is None:
        return ()
    if single.ambiguous:
        return ()
    return (single,)


def allowed_labels_for_region(region_name: str) -> tuple[str, ...]:
    return REGION_SLOT_LABELS.get(region_name, LEGAL_ACTION_LABELS)


def legal_action_to_recommended(label: str) -> RecommendedAction:
    if label in {"bet", "raise"}:
        return RecommendedAction.RAISE
    return RecommendedAction(label)


def expected_label_for_button_region(region_name: str) -> str | None:
    if not region_name.endswith("_button_region"):
        return None
    label = region_name[: -len("_button_region")]
    if label in LEGAL_ACTION_LABELS:
        return label
    return None


def merge_normalized_actions(
    actions: tuple[NormalizedLegalAction, ...],
) -> tuple[RecommendedAction, ...]:
    merged: list[RecommendedAction] = []
    seen: set[RecommendedAction] = set()
    for action in actions:
        if action.ambiguous:
            continue
        recommended = legal_action_to_recommended(action.label)
        if recommended in seen:
            continue
        merged.append(recommended)
        seen.add(recommended)
    return tuple(merged)


def parse_legal_actions_from_text(text: str) -> tuple[RecommendedAction, ...]:
    """Legacy line-based parser kept for log OCR fallback."""

    normalized = normalize_action_text(text)
    if normalized is None or normalized.ambiguous:
        return ()
    return (legal_action_to_recommended(normalized.label),)


def parse_legal_actions_from_lines(lines: tuple[str, ...]) -> tuple[RecommendedAction, ...]:
    actions, _, _, ambiguous = collect_legal_actions_from_lines(lines)
    if ambiguous:
        return ()
    return actions


def collect_legal_actions_from_lines(
    lines: tuple[str, ...],
) -> tuple[tuple[RecommendedAction, ...], tuple[str, ...], tuple[str, ...], bool]:
    merged: list[RecommendedAction] = []
    raw_texts: list[str] = []
    normalized: list[str] = []
    seen: set[RecommendedAction] = set()
    ambiguous = False
    for line in lines:
        if not line.strip():
            continue
        for action in extract_actions_from_region_text(line):
            raw_texts.append(action.raw_text)
            if action.ambiguous:
                ambiguous = True
                continue
            normalized.append(action.label)
            recommended = legal_action_to_recommended(action.label)
            if recommended in seen:
                continue
            merged.append(recommended)
            seen.add(recommended)
    return tuple(merged), tuple(raw_texts), tuple(normalized), ambiguous
