import unittest

from torn_accessibility_hud.models import ActionType, GameSnapshot, ParsedEvent
from torn_accessibility_hud.state import CardReadStabilizer, StickyCardCache


class CardReadStabilizerTests(unittest.TestCase):
    def test_requires_consecutive_reads_before_publishing(self) -> None:
        stabilizer = CardReadStabilizer(stable_reads_required=3)
        cards = ("8c", "2d")
        self.assertIsNone(stabilizer.observe("hero_cards_region", cards))
        self.assertIsNone(stabilizer.observe("hero_cards_region", cards))
        self.assertEqual(stabilizer.observe("hero_cards_region", cards), cards)
        self.assertIsNone(stabilizer.observe("hero_cards_region", cards))

    def test_failed_read_does_not_clear_published_cards(self) -> None:
        stabilizer = CardReadStabilizer(stable_reads_required=2)
        cards = ("8c", "2d")
        stabilizer.observe("hero_cards_region", cards)
        stabilizer.observe("hero_cards_region", cards)
        self.assertEqual(stabilizer.published("hero_cards_region"), cards)
        self.assertIsNone(stabilizer.observe("hero_cards_region", None))
        self.assertEqual(stabilizer.published("hero_cards_region"), cards)


class StickyCardCacheTests(unittest.TestCase):
    def test_hero_cache_survives_short_ocr_miss(self) -> None:
        cache = StickyCardCache(max_missing_scans=15)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        snapshot, changed = cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        self.assertFalse(changed)
        missed_snapshot = GameSnapshot()
        recovered, changed = cache.apply(missed_snapshot, (), hero_cards_scanned=True)
        self.assertTrue(changed)
        self.assertEqual(recovered.hero_cards, ("As", "Kd"))
        self.assertEqual(cache.hero_missing_scans, 1)

    def test_hero_cache_ignores_misses_when_region_not_scanned(self) -> None:
        cache = StickyCardCache(max_missing_scans=2)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        current = GameSnapshot()
        for _ in range(5):
            current, _changed = cache.apply(current, (), hero_cards_scanned=False)
        self.assertEqual(current.hero_cards, ("As", "Kd"))
        self.assertEqual(cache.hero_missing_scans, 0)

    def test_hero_cache_clears_after_missing_threshold(self) -> None:
        cache = StickyCardCache(max_missing_scans=2)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        current = GameSnapshot(hero_cards=("As", "Kd"))
        current, _changed = cache.apply(current, (), hero_cards_scanned=True)
        current, _changed = cache.apply(current, (), hero_cards_scanned=True)
        current, changed = cache.apply(current, (), hero_cards_scanned=True)
        self.assertTrue(changed)
        self.assertEqual(current.hero_cards, ())
        self.assertEqual(cache.cached_hero_cards, ())

    def test_board_cache_updates_and_survives_short_miss(self) -> None:
        cache = StickyCardCache(max_missing_scans=15)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"), board_cards=("2s", "4h", "Ks"))
        snapshot, changed = cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.BOARD, raw_text="Board: 2s 4h Ks", cards=("2s", "4h", "Ks")),),
        )
        self.assertFalse(changed)
        missing_board = GameSnapshot(hero_cards=("As", "Kd"))
        recovered, changed = cache.apply(missing_board, (), board_cards_scanned=True)
        self.assertTrue(changed)
        self.assertEqual(recovered.board_cards, ("2s", "4h", "Ks"))

    def test_hero_cache_preserves_cards_when_region_folded(self) -> None:
        cache = StickyCardCache(max_missing_scans=2)
        snapshot = GameSnapshot(hero_cards=("As", "Kd"))
        cache.apply(
            snapshot,
            (ParsedEvent(action=ActionType.DEALT_HERO, raw_text="Your hand: As Kd", cards=("As", "Kd")),),
        )
        cleared = GameSnapshot()
        for _ in range(5):
            cleared, _changed = cache.apply(cleared, (), hero_region_folded=True, hero_cards_scanned=True)
        self.assertEqual(cleared.hero_cards, ("As", "Kd"))
        self.assertEqual(cache.hero_missing_scans, 0)
        self.assertEqual(cache.cached_hero_cards, ("As", "Kd"))

    def test_new_hero_cards_clear_old_board_cache(self) -> None:
        cache = StickyCardCache(max_missing_scans=15)
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
