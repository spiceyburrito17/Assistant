import unittest

from torn_accessibility_hud.models import ScreenRegion
from torn_accessibility_hud.parsing.action_ui import detect_post_hand_ui, is_post_hand_ui
from torn_accessibility_hud.vision.button_region_layout import (
    format_region_coords,
    validate_action_slot_regions,
)


class ActionUiTests(unittest.TestCase):
    def test_detects_post_hand_ui(self) -> None:
        self.assertTrue(is_post_hand_ui("SHOW CARDS"))
        self.assertTrue(detect_post_hand_ui("FOLD", "SIT OUT LEAVE", None))


class ActionSlotRegionLayoutTests(unittest.TestCase):
    def test_format_region_coords(self) -> None:
        region = ScreenRegion(left=-838, top=893, width=212, height=45)
        self.assertEqual(format_region_coords(region), "-838,893,212,45")

    def test_rejects_wide_slot_regions(self) -> None:
        regions = {
            "action_slot_left": ScreenRegion(left=-1305, top=894, width=458, height=45),
            "action_slot_centre": ScreenRegion(left=-1095, top=894, width=200, height=45),
            "action_slot_right": ScreenRegion(left=-838, top=893, width=212, height=45),
        }
        filtered, warnings = validate_action_slot_regions(regions)
        self.assertNotIn("action_slot_left", filtered)
        self.assertIn("action_slot_centre", filtered)
        self.assertTrue(any("width" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
