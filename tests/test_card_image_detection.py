import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from torn_accessibility_hud.config import OCRConfig
from torn_accessibility_hud.models import OCRLine, ScreenRegion
from torn_accessibility_hud.vision.ocr_engine import (
    CardRegionDebugger,
    detect_cards_from_ocr_bboxes,
    detect_cards_from_region,
    detect_suit_from_card_image,
    detect_suit_from_card_image_with_debug,
    detect_suit_near_rank_bbox,
    find_card_face_crops_with_debug,
    format_raw_ocr_debug_lines,
    is_probably_card_back,
    is_probably_folded_hero_region,
    normalize_card_rank,
)


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

    def test_card_debug_header_is_written_before_detector_details(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            debugger = CardRegionDebugger(
                OCRConfig(
                    calibrated_regions_path=None,
                    debug_card_regions=True,
                    debug_card_regions_dir=temp_dir,
                )
            )
            debugger.regions = {
                "hero_cards_region": ScreenRegion(left=0, top=0, width=140, height=100),
                "board_cards_region": ScreenRegion(left=0, top=0, width=386, height=99),
            }
            prefix = Path(temp_dir) / "frame_000123_hero_cards_region"
            raw = np.zeros((100, 140, 3), dtype=np.uint8)
            header = debugger._debug_header(123, "hero_cards_region", raw)
            debugger._write_debug_text(prefix, (*header, "[detector] test"))
            content = prefix.with_name(f"{prefix.name}_ocr.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(content[0], "=== card detector entered for frame 000123 region=hero_cards_region ===")
        self.assertIn("hero captured crop size: 140x100 px", content[1])
        self.assertIn("hero region size: 140x100 px", content[2])
        self.assertIn("board region size: 386x99 px", content[3])

    def test_card_debug_writes_are_skipped_when_debug_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            debugger = CardRegionDebugger(
                OCRConfig(
                    calibrated_regions_path=None,
                    debug_card_regions=False,
                    debug_card_regions_dir=temp_dir,
                )
            )
            self.assertTrue(debugger.regions_configured is False)
            self.assertFalse(debugger.debug_enabled)
            prefix = Path(temp_dir) / "frame_000001_hero_cards_region"
            raw = np.zeros((10, 10, 3), dtype=np.uint8)
            debugger._write_debug_text(prefix, ("line",))
            debugger._save_raw_debug_image(prefix, raw)
            self.assertFalse(list(Path(temp_dir).iterdir()))

    def test_card_debugger_uses_explicit_hero_region_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            regions_path = Path(temp_dir) / "regions.json"
            regions_path.write_text(
                json.dumps(
                    {
                        "hero_cards_region": {"left": 10, "top": 20, "width": 30, "height": 40},
                        "board_cards_region": {"left": 50, "top": 60, "width": 70, "height": 80},
                    }
                ),
                encoding="utf-8",
            )
            debugger = CardRegionDebugger(
                OCRConfig(
                    calibrated_regions_path=str(regions_path),
                    hero_cards_region=ScreenRegion(left=1, top=2, width=3, height=4),
                    debug_card_regions_dir=temp_dir,
                    hero_cards_interval_sec=0.25,
                )
            )
        self.assertEqual(debugger.regions["hero_cards_region"].left, 1)
        self.assertEqual(debugger.regions["hero_cards_region"].width, 3)
        self.assertEqual(debugger.regions["board_cards_region"].left, 50)
        self.assertEqual(debugger._interval_for_region("hero_cards_region"), 0.25)

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_bbox_fallback_constructs_cards_from_rank_ocr_lines(self) -> None:
        region = np.full((120, 180, 3), 245, dtype=np.uint8)
        region[35:52, 15:32] = (0, 0, 190)
        region[35:52, 95:112] = (0, 150, 0)
        lines = (
            OCRLine(text="8", confidence=0.97, bbox=((45, 60), (72, 60), (72, 84), (45, 84))),
            OCRLine(text="A", confidence=0.91, bbox=((285, 60), (312, 60), (312, 84), (285, 84))),
        )
        cards, debug_lines = detect_cards_from_ocr_bboxes(region, lines, ocr_scale=3.0)
        self.assertEqual(cards, ("8h", "Ac"))
        self.assertTrue(any("ACCEPTED card=8h" in line for line in debug_lines))
        self.assertTrue(any("ACCEPTED card=Ac" in line for line in debug_lines))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_suit_roi_near_rank_bbox_uses_scaled_coordinates(self) -> None:
        region = np.full((80, 80, 3), 245, dtype=np.uint8)
        region[24:40, 12:28] = (210, 80, 0)
        suit, debug_lines = detect_suit_near_rank_bbox(
            region,
            bbox=((30, 18), (66, 18), (66, 48), (30, 48)),
            ocr_scale=3.0,
        )
        self.assertEqual(suit, "d")
        self.assertTrue(any("rank_bbox_raw" in line for line in debug_lines))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_detect_suit_from_colored_glyphs(self) -> None:
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((0, 0, 210))), "h")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((210, 80, 0))), "d")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((0, 160, 0))), "c")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((20, 20, 20))), "s")
        self.assertEqual(detect_suit_from_card_image(self._card_with_glyph((210, 210, 210))), "s")

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_suit_debug_logs_dominant_color_when_detection_fails(self) -> None:
        suit, debug_lines = detect_suit_from_card_image_with_debug(np.full((60, 40, 3), 115, dtype=np.uint8))
        self.assertIsNone(suit)
        self.assertTrue(any("dominant_bgr" in line for line in debug_lines))
        self.assertTrue(any("scores hearts=" in line for line in debug_lines))
        self.assertTrue(any("FAILED" in line for line in debug_lines))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_folded_guard_distinguishes_live_hero_from_grey_overlay(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "card_regions" / "hero_cards_region_raw.png"
        if fixture.exists():
            import cv2

            live = cv2.imread(str(fixture))
            self.assertFalse(is_probably_folded_hero_region(live))
        folded = np.full((90, 120, 3), 135, dtype=np.uint8)
        folded[18:24, :] = 70
        self.assertTrue(is_probably_folded_hero_region(folded))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_card_back_and_folded_hero_guards(self) -> None:
        face_up = self._card_with_glyph((0, 0, 210))
        patterned_back = np.full((80, 55, 3), 120, dtype=np.uint8)
        patterned_back[:, ::4] = 230
        self.assertFalse(is_probably_card_back(face_up))
        self.assertFalse(is_probably_folded_hero_region(face_up))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_suit_prefers_colored_glyphs_over_white_background(self) -> None:
        face_up = np.full((80, 55, 3), 245, dtype=np.uint8)
        face_up[12:28, 12:28] = (0, 160, 0)
        self.assertEqual(detect_suit_from_card_image(face_up), "c")

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    def test_find_card_face_crops_splits_merged_hero_row(self) -> None:
        fixture = Path(__file__).resolve().parent / "fixtures" / "card_regions" / "hero_cards_region_raw.png"
        if not fixture.exists():
            self.skipTest("hero card fixture image is unavailable")
        import cv2

        raw = cv2.imread(str(fixture))
        crops, debug_lines = find_card_face_crops_with_debug(raw)
        self.assertEqual(len(crops), 2)
        self.assertTrue(any("split fallback" in line for line in debug_lines))

    @unittest.skipIf(importlib.util.find_spec("cv2") is None, "opencv-python is not installed")
    @unittest.skipIf(importlib.util.find_spec("easyocr") is None, "easyocr is not installed")
    def test_detect_cards_from_torn_fixture_regions(self) -> None:
        from torn_accessibility_hud.config import OCRConfig
        from torn_accessibility_hud.vision.ocr_engine import EasyOCREngine, preprocess_card_region

        fixtures = Path(__file__).resolve().parent / "fixtures" / "card_regions"
        hero_path = fixtures / "hero_cards_region_raw.png"
        board_path = fixtures / "board_cards_region_raw.png"
        if not hero_path.exists() or not board_path.exists():
            self.skipTest("card region fixture images are unavailable")
        import cv2

        ocr = EasyOCREngine(OCRConfig())
        for path, expected in (
            (hero_path, ("7d", "Qc")),
            (board_path, ("Jh", "9d", "5h")),
        ):
            raw = cv2.imread(str(path))
            processed = preprocess_card_region(raw, scale=3.0)
            region_ocr = ocr.read_raw(processed, allowlist="A23456789TJQK10cdhsCDHS")
            cards, _debug_lines = detect_cards_from_region(
                raw,
                ocr,
                scale=3.0,
                fallback_ocr_lines=region_ocr,
                fallback_ocr_scale=3.0,
            )
            self.assertEqual(cards, expected)

    @staticmethod
    def _card_with_glyph(color_bgr: tuple[int, int, int]) -> np.ndarray:
        card = np.full((80, 55, 3), 245, dtype=np.uint8)
        card[12:28, 12:28] = color_bgr
        return card


if __name__ == "__main__":
    unittest.main()
