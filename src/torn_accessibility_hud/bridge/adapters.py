"""Map bridge payloads into ``GameSnapshot`` updates (bypasses OCR parsers)."""

from __future__ import annotations

from dataclasses import replace

from ..models import GameSnapshot, RecommendedAction, TableStateConfidence

from .payload import BridgeTableUpdate, GameStatePayload


def apply_bridge_update(
    snapshot: GameSnapshot,
    update: BridgeTableUpdate,
) -> GameSnapshot:
    """Apply a deterministic DOM payload directly to the running snapshot."""

    payload = update.payload
    generation = snapshot.generation
    changed = payload.fingerprint() != _snapshot_fingerprint(snapshot, payload)

    hero_cards = payload.hero_cards or snapshot.hero_cards
    board_cards = payload.board_cards or snapshot.board_cards
    pot_size = payload.pot if payload.pot is not None else snapshot.pot_size
    to_call = payload.to_call if payload.to_call is not None else snapshot.to_call

    legal_actions: tuple[RecommendedAction, ...]
    if payload.hero_turn and payload.legal_actions:
        legal_actions = payload.recommended_actions()
    elif not payload.hero_turn:
        legal_actions = ()
    else:
        legal_actions = snapshot.legal_actions

    if changed:
        generation += 1

    return replace(
        snapshot,
        hero_cards=hero_cards,
        board_cards=board_cards,
        pot_size=pot_size or 0.0,
        to_call=max(0.0, to_call or 0.0),
        street=payload.street,
        legal_actions=legal_actions,
        state_confidence=update.state_confidence,
        actions_ambiguous=False,
        parse_diagnostics=payload.to_parse_diagnostics(),
        generation=generation,
    )


def _snapshot_fingerprint(snapshot: GameSnapshot, payload: GameStatePayload) -> tuple[object, ...]:
    return (
        snapshot.pot_size,
        snapshot.to_call,
        snapshot.hero_cards,
        snapshot.board_cards,
        tuple(action.value for action in snapshot.legal_actions),
        payload.hero_turn,
    )
