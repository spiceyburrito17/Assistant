"""Tests for v2 stable event labels."""

from __future__ import annotations

import unittest

from torn_hud_v2.constants import (
    SESSION_EVENT_PRIORITY,
    SESSION_EVENT_TYPE_LABELS,
    SessionEventType,
    format_event_types,
)


class EventLabelTests(unittest.TestCase):
    def test_stable_labels_match_enum_values(self) -> None:
        self.assertEqual(
            SESSION_EVENT_TYPE_LABELS,
            tuple(event.value for event in SESSION_EVENT_PRIORITY),
        )
        self.assertEqual(len(SESSION_EVENT_TYPE_LABELS), len(set(SESSION_EVENT_TYPE_LABELS)))

    def test_priority_order_is_explicit(self) -> None:
        self.assertEqual(
            [event.value for event in SESSION_EVENT_PRIORITY],
            [
                "street_change",
                "hero_turn",
                "actions_update",
                "decision",
                "blocked",
            ],
        )

    def test_format_event_types_orders_labels(self) -> None:
        formatted = format_event_types(
            {
                SessionEventType.DECISION,
                SessionEventType.HERO_TURN,
                SessionEventType.STREET_CHANGE,
            }
        )
        self.assertEqual(formatted, "street_change|hero_turn|decision")


if __name__ == "__main__":
    unittest.main()
