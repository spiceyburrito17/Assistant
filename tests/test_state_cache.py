import unittest

from torn_accessibility_hud.models import ActionType, GameSnapshot, ParsedEvent
from torn_accessibility_hud.state import StickyCardCache


class StickyCardCacheTests(unittest.TestCase):
    def test_hero_cache_survives_short_ocr_miss(self) -> None:
        cache = StickyCardCache(max_missing_frames=15)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        snapshot, changed = cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        self.assertFalse(changed)
        missed_snapshot = GameSnapshot()
        recovered, changed = cache.apply(missed_snapshot, ())
        self.assertTrue(changed)
        self.assertEqual(recovered.hero_cards, ("As", "Kd"))
        self.assertEqual(cache.hero_missing_frames, 1)

    def test_hero_cache_clears_after_missing_threshold(self) -> None:
        cache = StickyCardCache(max_missing_frames=2)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        current = GameSnapshot(hero_cards=("As", "Kd"))
        current, _changed = cache.apply(current, ())
        current, _changed = cache.apply(current, ())
        current, changed = cache.apply(current, ())
        self.assertTrue(changed)
        self.assertEqual(current.hero_cards, ())
        self.assertEqual(cache.cached_hero_cards, ())

    def test_board_cache_updates_and_survives_short_miss(self) -> None:
        cache = StickyCardCache(max_missing_frames=15)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h", "Ks"))
        snapshot, changed = cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.BOARD, raw_text="Board: 2s 4h Ks", cards=("2s", "4h", "Ks")),),
        )
        self.assertFalse(changed)
        missing_board = GameSnapshot(hero_cards=("As", "Kd"))
        recovered, changed = cache.apply(missing_board, ())
        self.assertTrue(changed)
        self.assertEqual(recovered.board_cards, ("2s", "4h", "Ks"))

    def test_new_hero_cards_clear_old_board_cache(self) -> None:
        cache = StickyCardCache(max_missing_frames=15)
        cache.apply(
            GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h", "Ks")),
            (
                ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),
                ParsedEvent(action=ActionType.BOARD, raw_text="Board: 2s 4h Ks", cards=("2s", "4h", "Ks")),
            ),
        )
        cache.apply(
            GameSnapshot(hero_cards=("Qh", "Jd")),
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: Qh Jd", cards=("Qh", "Jd")),),
        )
        self.assertEqual(cache.cached_board_cards, ())


if __name__ == "__main__":
    unittest.main()
