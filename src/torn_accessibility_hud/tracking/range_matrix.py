"""A conservative 169-class Texas Hold'em opponent range matrix."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Mapping

from ..models import ActionType, Street
from ..parsing.cards import FULL_DECK, RANKS, canonical_hand_class


def _build_hand_classes() -> tuple[str, ...]:
    classes: list[str] = []
    for high in reversed(RANKS):
        for low in reversed(RANKS):
            if high == low:
                classes.append(f"{high}{low}")
            elif RANKS.index(high) > RANKS.index(low):
                classes.append(f"{high}{low}s")
                classes.append(f"{high}{low}o")
    return tuple(dict.fromkeys(classes))


HAND_CLASSES = _build_hand_classes()


@dataclass
class RangeMatrix:
    """Mutable hand-class weights for one opponent."""

    weights: dict[str, float] = field(default_factory=lambda: {hand: 1.0 for hand in HAND_CLASSES})

    def copy_weights(self) -> dict[str, float]:
        total = sum(max(weight, 0.0) for weight in self.weights.values())
        if total <= 0:
            return {hand: 1.0 / len(HAND_CLASSES) for hand in HAND_CLASSES}
        return {hand: max(weight, 0.0) / total for hand, weight in self.weights.items()}

    def apply_action(self, action: ActionType, street: Street, amount: float | None = None) -> None:
        if street is not Street.PREFLOP:
            self._apply_postflop_pressure(action, amount)
            return
        if action in {ActionType.CALL, ActionType.BET}:
            self._scale_by_threshold(min_strength=0.42, premium_boost=1.25)
        elif action is ActionType.RAISE:
            self._scale_by_threshold(min_strength=0.58, premium_boost=1.85)
        elif action is ActionType.ALL_IN:
            self._scale_by_threshold(min_strength=0.72, premium_boost=2.4)
        elif action is ActionType.CHECK:
            self._scale_by_threshold(min_strength=0.0, premium_boost=0.92)
        elif action is ActionType.FOLD:
            self._scale_all(0.15)
        self._renormalize_floor()

    def top_classes(self, limit: int = 8) -> tuple[str, ...]:
        normalized = self.copy_weights()
        return tuple(hand for hand, _ in sorted(normalized.items(), key=lambda item: item[1], reverse=True)[:limit])

    def sample_combo(self, excluded_cards: set[str], rng: random.Random) -> tuple[str, str] | None:
        available = [card for card in FULL_DECK if card not in excluded_cards]
        combos: list[tuple[str, str]] = []
        combo_weights: list[float] = []
        normalized = self.copy_weights()
        for idx, first in enumerate(available):
            for second in available[idx + 1 :]:
                hand_class = canonical_hand_class(first, second)
                weight = normalized.get(hand_class, 0.0)
                if weight <= 0:
                    continue
                combos.append((first, second))
                combo_weights.append(weight)
        if not combos:
            return None
        return rng.choices(combos, weights=combo_weights, k=1)[0]

    @classmethod
    def from_weights(cls, weights: Mapping[str, float]) -> "RangeMatrix":
        matrix = cls()
        for hand in HAND_CLASSES:
            matrix.weights[hand] = max(float(weights.get(hand, 0.0)), 0.0)
        matrix._renormalize_floor()
        return matrix

    def _scale_by_threshold(self, min_strength: float, premium_boost: float) -> None:
        for hand in list(self.weights):
            strength = hand_strength_score(hand)
            if strength < min_strength:
                self.weights[hand] *= max(0.08, strength / max(min_strength, 0.01))
            else:
                self.weights[hand] *= 1.0 + (strength * premium_boost)

    def _apply_postflop_pressure(self, action: ActionType, amount: float | None) -> None:
        pressure = 1.0
        if action is ActionType.BET:
            pressure = 1.15
        elif action is ActionType.RAISE:
            pressure = 1.35
        elif action is ActionType.ALL_IN:
            pressure = 1.8
        elif action is ActionType.FOLD:
            pressure = 0.2
        for hand in list(self.weights):
            strength = hand_strength_score(hand)
            self.weights[hand] *= 0.9 + strength * pressure
        if amount is not None and amount > 0:
            self._scale_by_threshold(min_strength=0.50, premium_boost=min(2.0, 1.0 + amount / 10000.0))
        self._renormalize_floor()

    def _scale_all(self, factor: float) -> None:
        for hand in list(self.weights):
            self.weights[hand] *= factor

    def _renormalize_floor(self) -> None:
        for hand in list(self.weights):
            if self.weights[hand] < 1e-9:
                self.weights[hand] = 1e-9


def hand_strength_score(hand_class: str) -> float:
    """Heuristic 0..1 score used for range tightening."""

    high = RANKS.index(hand_class[0]) + 2
    low = RANKS.index(hand_class[1]) + 2
    if len(hand_class) == 2:
        pair_bonus = 22 + high * 3
        return min(1.0, pair_bonus / 60.0)
    suited_bonus = 5 if hand_class.endswith("s") else 0
    connector_bonus = max(0, 5 - abs(high - low))
    broadway_bonus = 8 if high >= 11 and low >= 10 else 0
    ace_bonus = 5 if high == 14 else 0
    raw = high * 2.4 + low * 1.3 + suited_bonus + connector_bonus + broadway_bonus + ace_bonus
    return min(1.0, raw / 62.0)
