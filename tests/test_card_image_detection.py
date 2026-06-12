import importlib.util
import unittest

import numpy as np

from torn_accessibility_hud.vision.ocr_engine import (
    detect_suit_from_card_image,
    format_raw_ocr_debug_lines,
    is_probably_card_back,
    is_probably_folded_hero_region,
    normalize_card_rank,
)
from torn_accessibility_hud.models import OCRLine


class CardImageDetectionTests(unittest.TestCase):
    def test_normalize_card_rank_handles_ten_ocr_variants(self) -> None:
        self.assertEqual(normalize_card_rank("10"), "T")
        self.assertEqual(normalize_card_rank("1O"), "T")
        self.assertEqual(normalize_card_rank("I0"), "T")
        self.assertEqual(normalize_card_rank("1"), "T")

    def test_format_raw_ocr_debug_lines_includes_empty_and_bbox_details(self) -> None:
        empty = format_raw_ocr_debug_lines("rank", (), allowlist="0123")
        self.assertIn("raw_count=0", empty[0])
        self.assertIn("no raw OCR results", empty[1])
        populated = format_raw_ocr_debug_lines(
            "rank",
            (OCRLine(text="6", confidence=0.151, bbox=((1, 2), (3, 4), (5, 6), (7, 8))),),
            allowlist="0123",
        )
        self.assertIn("text='6'", populated[1])
        self.assertIn("confidence=0.1510", populated[1])
        self.assertIn("bbox=((1, 2), (3, 4), (5, 6), (7, 8))", populated[1])

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_detect_suit_from_colored_glyphs(self) -> None:
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((0, 0, 210))), "h")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((210, 80, 0))), "d")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((0, 160, 0))), "c")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((20, 20, 20))), "s")

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_card_back_and_folded_hero_guards(self) -> None:
        face_up = self._card_with_glyph((0, 0, 210))
        patterned_back = np.full((80, 55, 3), 120, dtype=np.uint8)
        patterned_back[:, ::4] = 230
        folded = np.full((90, 120, 3), 135, dtype=np.uint8)
        folded[18:24, :] = 70
        self.assertFalse(is_probably_card_back(face_up))
        self.assertTrue(is_probably_card_back(patterned_back))
        self.assertTrue(is_probably_folded_hero_region(folded))

    @staticmethod
    def _card_with_glyph(color_bgr: tuple[int, int, int]) -> np.ndarray:
        card = np.full((80, 55, 3), 245, dtype=np.uint8)
        card[12:28, 12:28] = color_bgr
        return card


if __name__ == "__main__":
    unittest.main()
