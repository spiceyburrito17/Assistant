"""Card and OCR normalization utilities."""

from __future__ import annotations

import re
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
FULL_DECK = tuple(f"{rank}{suit}" for rank in RANKS for suit in SUITS)

_CARD_RE = re.compile(r"(?<![a-z0-9])(10|[2-9tjqka])\s*([cdhs♣♦♥♠])", re.IGNORECASE)
_RANK_TRANSLATION = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
        "|": "1",
    }
)
_SUIT_WORDS = {
    "clubs": "c",
    "club": "c",
    "diamonds": "d",
    "diamond": "d",
    "hearts": "h",
    "heart": "h",
    "spades": "s",
    "spade": "s",
}
_SUIT_SYMBOLS = {"♣": "c", "♦": "d", "♥": "h", "♠": "s"}


def normalize_ocr_text(text: str) -> str:
    """Normalize OCR text while preserving player-name readability."""

    cleaned = " ".join(text.replace("\n", " ").split())
    for word, suit in _SUIT_WORDS.items():
        cleaned = re.sub(rf"\b{word}\b", suit, cleaned, flags=re.IGNORECASE)
    return cleaned


def parse_cards(text: str) -> tuple[str, ...]:
    """Extract unique treys-compatible card strings such as ``As`` and ``Td``."""

    normalized = normalize_ocr_text(text).translate(_RANK_TRANSLATION)
    cards: list[str] = []
    seen: set[str] = set()
    for rank_raw, suit_raw in _CARD_RE.findall(normalized):
        rank = rank_raw.upper()
        suit = _SUIT_SYMBOLS.get(suit_raw, suit_raw).lower()
        if rank == "10":
            rank = "T"
        card = f"{rank}{suit}"
        if rank in RANKS and suit in SUITS and card not in seen:
            cards.append(card)
            seen.add(card)
    return tuple(cards)


def validate_cards(cards: tuple[str, ...], max_cards: int | None = None) -> bool:
    if max_cards is not None and len(cards) > max_cards:
        return False
    return len(cards) == len(set(cards)) and all(card in FULL_DECK for card in cards)


def remaining_cards(excluded: set[str]) -> tuple[str, ...]:
    return tuple(card for card in FULL_DECK if card not in excluded)


def available_combos(excluded: set[str]) -> tuple[tuple[str, str], ...]:
    return tuple(combinations(remaining_cards(excluded), 2))


def canonical_hand_class(card_a: str, card_b: str) -> str:
    """Return a 169-matrix hand class, e.g. AA, AKs, or T9o."""

    rank_a, suit_a = card_a[0], card_a[1]
    rank_b, suit_b = card_b[0], card_b[1]
    if rank_a == rank_b:
        return f"{rank_a}{rank_b}"
    high, low = sorted((rank_a, rank_b), key=RANKS.index, reverse=True)
    suitedness = "s" if suit_a == suit_b else "o"
    return f"{high}{low}{suitedness}"
