import unittest

from torn_accessibility_hud.models import (
    ActionType,
    ActionSlotOCRResult,
    GameSnapshot,
    ParsedEvent,
    TableOCRResult,
)
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

    def test_post_hand_ui_skips_action_parsing(self) -> None:
        manager = TrustedTableStateManager()
        manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), pot_size=500.0),
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
            (),
            hero_cards_scanned=True,
            hero_cards_stable=True,
        )
        table_ocr = TableOCRResult(
            slots=(
                ActionSlotOCRResult(
                    slot_name="action_slot_centre",
                    ocr_scan_raw="SHOW CARDS SIT OUT LEAVE",
                    region_coords="-1095,894,200,45",
                ),
            ),
            action_regions_scanned=True,
            post_hand_ui=True,
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd"), pot_size=500.0),
            (),
            (),
            hero_cards_scanned=True,
            hero_cards_stable=True,
            table_ocr=table_ocr,
        )
        self.assertTrue(trusted.parse_diagnostics is not None)
        assert trusted.parse_diagnostics is not None
        self.assertTrue(trusted.parse_diagnostics.post_hand_ui)
        self.assertEqual(trusted.parse_diagnostics.block_reason, "post_hand")
        self.assertEqual(snapshot.legal_actions, ())


if __name__ == "__main__":
    unittest.main()
