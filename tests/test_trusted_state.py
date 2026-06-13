import unittest

from torn_accessibility_hud.models import ActionType, GameSnapshot, ParsedEvent
from torn_accessibility_hud.state import TrustedTableStateManager


class TrustedTableStateManagerTests(unittest.TestCase):
    def test_hero_survives_short_ocr_miss(self) -> None:
        manager = TrustedTableStateManager(hero_missing_grace_scans=15)
        manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
            (),
        )
        trusted, snapshot = manager.apply(GameSnapshot(), (), (), hero_cards_scanned=True)
        self.assertEqual(snapshot.hero_cards, ("As", "Kd"))
        self.assertEqual(manager.trusted.hero_cards, ("As", "Kd"))

    def test_board_only_regresses_after_threshold(self) -> None:
        manager = TrustedTableStateManager(board_regress_scans=2)
        manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h", "Ks")),
            (
                ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),
                ParsedEvent(action=ActionType.BOARD, raw_text="Board: 2s 4h Ks", cards=("2s", "4h", "Ks")),
            ),
            (),
        )
        for _ in range(3):
            manager.apply(
                GameSnapshot(hero_cards=("As", "Kd")),
                (),
                (),
                board_cards_scanned=True,
            )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            board_cards_scanned=True,
        )
        self.assertEqual(snapshot.board_cards, ())


if __name__ == "__main__":
    unittest.main()
