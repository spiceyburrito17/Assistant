import unittest

from torn_accessibility_hud.models import ActionType, ParsedEvent, Street
from torn_accessibility_hud.tracking.ledger import OpponentLedger
from torn_accessibility_hud.tracking.range_matrix import RangeMatrix


class TrackingTests(unittest.TestCase):
    def test_ledger_tracks_vpip_and_pfr_once_per_hand(self) -> None:
        ledger = OpponentLedger()
        ledger.process_event(ParsedEvent(action=ActionType.DEALT_HERO, raw_text="You were dealt As Kd"))
        ledger.process_event(
            ParsedEvent(action=ActionType.CALL, raw_text="Fox calls 100", player_name="Fox", amount=100)
        )
        ledger.process_event(
            ParsedEvent(action=ActionType.RAISE, raw_text="Fox raises to 400", player_name="Fox", amount=400)
        )
        stats = ledger.public_stats()[0]
        self.assertEqual(stats.hands_seen, 1)
        self.assertEqual(stats.vpip, 1.0)
        self.assertEqual(stats.pfr, 1.0)
        self.assertIn("Fox", ledger.active_opponents)

    def test_fold_removes_active_opponent(self) -> None:
        ledger = OpponentLedger()
        ledger.process_event(ParsedEvent(action=ActionType.DEALT_HERO, raw_text="You were dealt As Kd"))
        ledger.process_event(
            ParsedEvent(action=ActionType.CALL, raw_text="Fox calls 100", player_name="Fox", amount=100)
        )
        ledger.process_event(ParsedEvent(action=ActionType.FOLD, raw_text="Fox folds", player_name="Fox"))
        self.assertNotIn("Fox", ledger.active_opponents)

    def test_raise_tightens_range_toward_premium_hands(self) -> None:
        matrix = RangeMatrix()
        before = matrix.copy_weights()
        matrix.apply_action(ActionType.RAISE, Street.PREFLOP, 500)
        after = matrix.copy_weights()
        self.assertGreater(after["AA"], before["AA"])
        self.assertLess(after["72o"], before["72o"])


if __name__ == "__main__":
    unittest.main()
