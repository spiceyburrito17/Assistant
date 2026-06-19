import unittest

from torn_accessibility_hud.models import GameSnapshot, PotOCRResult, TableOCRResult
from torn_accessibility_hud.parsing.pot_parser import parse_pot_region_text, parse_pot_text, parse_pot_text_detailed
from torn_accessibility_hud.parsing.pot_sanity import validate_pot_update
from torn_accessibility_hud.state import TrustedTableStateManager


class PotParserTests(unittest.TestCase):
    def test_pot_dollar_660(self) -> None:
        amount, status = parse_pot_text("POT: $660")
        self.assertEqual(amount, 660.0)
        self.assertEqual(status, "ok")

    def test_misread_dollar_as_prefix_five(self) -> None:
        amount, status = parse_pot_text("POT: 5660")
        self.assertEqual(amount, 660.0)
        self.assertEqual(status, "ok")

    def test_plain_three_digit_pot_without_prefix_skip(self) -> None:
        amount, status = parse_pot_text("POT: 540")
        self.assertEqual(amount, 540.0)
        self.assertEqual(status, "ok")

    def test_comma_formatted_pot(self) -> None:
        amount, status = parse_pot_text("POT: $2,400")
        self.assertEqual(amount, 2400.0)
        self.assertEqual(status, "ok")

    def test_ignores_junk_after_first_amount(self) -> None:
        result = parse_pot_text_detailed("POT: $2,4008281400")
        self.assertEqual(result.candidate, "2,400")
        self.assertEqual(result.normalized, 2400.0)

    def test_keeps_normal_three_digit_pot(self) -> None:
        amount, status = parse_pot_text("POT: 675")
        self.assertEqual(amount, 675.0)
        self.assertEqual(status, "ok")

    def test_prefix_debug_indices(self) -> None:
        result = parse_pot_text_detailed("POT: 5660")
        self.assertEqual(result.pot_anchor_match, "POT")
        self.assertEqual(result.pot_anchor_confidence, 1.0)
        self.assertEqual(result.pot_digits_start, 6)
        self.assertEqual(result.candidate, "660")

    def test_fuzzy_anchor_poi(self) -> None:
        amount, status = parse_pot_text("POI: $660")
        self.assertEqual(amount, 660.0)
        self.assertEqual(status, "ok")

    def test_fuzzy_anchor_po7(self) -> None:
        amount, status = parse_pot_text("PO7: 5660")
        self.assertEqual(amount, 660.0)
        self.assertEqual(status, "ok")

    def test_fuzzy_anchor_p0t(self) -> None:
        amount, status = parse_pot_text("P0T: $540")
        self.assertEqual(amount, 540.0)
        self.assertEqual(status, "ok")

    def test_weak_fuzzy_anchor_with_short_digits_rejects(self) -> None:
        result = parse_pot_text_detailed("POI: 63")
        self.assertIsNone(result.normalized)
        self.assertEqual(result.status, "weak_anchor_and_digits")
        self.assertEqual(result.candidate, "63")

    def test_digit_encoded_pot_anchor_from_restricted_ocr(self) -> None:
        result = parse_pot_text_detailed("816440")
        self.assertEqual(result.normalized, 440.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.pot_anchor_match, "816")
        self.assertEqual(result.pot_anchor_confidence, 0.55)
        self.assertEqual(result.pot_digits_start, 3)
        self.assertEqual(result.candidate, "440")

    def test_digit_encoded_anchor_with_short_amount_rejects(self) -> None:
        result = parse_pot_text_detailed("81663")
        self.assertIsNone(result.normalized)
        self.assertEqual(result.status, "weak_anchor_and_digits")
        self.assertEqual(result.candidate, "63")

    def test_no_pot_marker_rejects(self) -> None:
        result = parse_pot_region_text("5660")
        self.assertIsNone(result.normalized)
        self.assertEqual(result.status, "no_pot_marker")

    def test_does_not_fabricate_middle_four_correction(self) -> None:
        amount, status = parse_pot_text("POT: 545")
        self.assertEqual(amount, 545.0)
        self.assertEqual(status, "ok")

    def test_misread_dollar_as_five_before_short_amount(self) -> None:
        result = parse_pot_text_detailed("POT 585")
        self.assertEqual(result.normalized, 85.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.candidate, "85")
        self.assertEqual(result.pot_anchor_match, "POT")

    def test_misread_dollar_as_five_before_two_digit_amount_with_colon(self) -> None:
        amount, status = parse_pot_text("POT: 585")
        self.assertEqual(amount, 85.0)
        self.assertEqual(status, "ok")

    def test_misread_dollar_as_six_before_amount(self) -> None:
        result = parse_pot_text_detailed("POT 6190")
        self.assertEqual(result.normalized, 190.0)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.candidate, "190")
        self.assertEqual(result.pot_anchor_match, "POT")
        self.assertEqual(result.pot_digits_start, 5)

    def test_misread_dollar_as_six_with_label_punctuation(self) -> None:
        amount, status = parse_pot_text("POT: 6190")
        self.assertEqual(amount, 190.0)
        self.assertEqual(status, "ok")

    def test_real_pot_starting_with_six_not_stripped(self) -> None:
        amount, status = parse_pot_text("POT: 600")
        self.assertEqual(amount, 600.0)
        self.assertEqual(status, "ok")

    def test_misread_dollar_before_comma_amount(self) -> None:
        result = parse_pot_text_detailed("POT51,145")
        self.assertEqual(result.normalized, 1145.0)
        self.assertEqual(result.candidate, "1,145")
        self.assertEqual(result.status, "ok")

    def test_misread_dollar_as_eight_before_amount(self) -> None:
        result = parse_pot_text_detailed("POT 8120")
        self.assertEqual(result.normalized, 120.0)
        self.assertEqual(result.candidate, "120")
        self.assertEqual(result.status, "ok")

    def test_misread_dollar_as_eight_with_label_punctuation(self) -> None:
        amount, status = parse_pot_text("POT: 8120")
        self.assertEqual(amount, 120.0)
        self.assertEqual(status, "ok")

    def test_comma_formatted_pot_starting_with_eight_not_stripped(self) -> None:
        amount, status = parse_pot_text("POT: 8,120")
        self.assertEqual(amount, 8120.0)
        self.assertEqual(status, "ok")

    def test_comma_formatted_pot_starting_with_five_not_stripped(self) -> None:
        amount, status = parse_pot_text("POT: 5,120")
        self.assertEqual(amount, 5120.0)
        self.assertEqual(status, "ok")

    def test_four_digit_pot_without_comma_not_stripped_when_real(self) -> None:
        amount, status = parse_pot_text("POT: 5120")
        self.assertEqual(amount, 5120.0)
        self.assertEqual(status, "ok")

    def test_large_comma_formatted_pot_not_stripped(self) -> None:
        amount, status = parse_pot_text("POT: 81,200")
        self.assertEqual(amount, 81200.0)
        self.assertEqual(status, "ok")


class PotSanityTests(unittest.TestCase):
    def test_rejects_absurd_jump(self) -> None:
        accepted, reason = validate_pot_update(8281400.0, previous=540.0, hand_reset=False)
        self.assertIsNone(accepted)
        self.assertIn("jump", reason or "")

    def test_rejects_decrease_within_hand(self) -> None:
        accepted, reason = validate_pot_update(400.0, previous=540.0, hand_reset=False)
        self.assertIsNone(accepted)
        self.assertEqual(reason, "pot decreased within hand")

    def test_allows_reset_hand(self) -> None:
        accepted, reason = validate_pot_update(50.0, previous=540.0, hand_reset=True)
        self.assertEqual(accepted, 50.0)
        self.assertIsNone(reason)

    def test_allows_leading_five_misread_correction(self) -> None:
        accepted, reason = validate_pot_update(85.0, previous=585.0, hand_reset=False)
        self.assertEqual(accepted, 85.0)
        self.assertIsNone(reason)

    def test_allows_leading_six_misread_correction(self) -> None:
        accepted, reason = validate_pot_update(190.0, previous=6190.0, hand_reset=False)
        self.assertEqual(accepted, 190.0)
        self.assertIsNone(reason)

    def test_table_region_allows_large_stale_correction(self) -> None:
        accepted, reason = validate_pot_update(
            1145.0,
            previous=33110.0,
            hand_reset=False,
            from_table_region=True,
        )
        self.assertEqual(accepted, 1145.0)
        self.assertIsNone(reason)

    def test_table_region_rejects_small_decrease(self) -> None:
        accepted, reason = validate_pot_update(
            800.0,
            previous=1145.0,
            hand_reset=False,
            from_table_region=True,
        )
        self.assertIsNone(accepted)
        self.assertEqual(reason, "pot decreased within hand")


class TrustedPotSanityTests(unittest.TestCase):
    def test_rejected_pot_keeps_previous_trusted_value(self) -> None:
        manager = TrustedTableStateManager()
        manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            table_ocr=TableOCRResult(
                pot=PotOCRResult(
                    raw_text="POT: $540",
                    parsed_amount=540.0,
                    ocr_confidence=0.9,
                    allowlist="$",
                    pot_candidate="540",
                    parse_status="ok",
                ),
                pot_region_scanned=True,
            ),
        )
        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            table_ocr=TableOCRResult(
                pot=PotOCRResult(
                    raw_text="POT: $2,4008281400",
                    parsed_amount=2400.0,
                    ocr_confidence=0.9,
                    allowlist="$",
                    pot_candidate="2,400",
                    parse_status="ok",
                ),
                pot_region_scanned=True,
            ),
        )
        self.assertEqual(trusted.pot_size, 2400.0)

        trusted, snapshot = manager.apply(
            GameSnapshot(hero_cards=("As", "Kd")),
            (),
            (),
            table_ocr=TableOCRResult(
                pot=PotOCRResult(
                    raw_text="POT: 8281400",
                    parsed_amount=8281400.0,
                    ocr_confidence=0.9,
                    allowlist="$",
                    pot_candidate="8281400",
                    parse_status="ok",
                ),
                pot_region_scanned=True,
            ),
        )
        self.assertEqual(trusted.pot_size, 2400.0)
        assert snapshot.parse_diagnostics is not None
        self.assertIsNotNone(snapshot.parse_diagnostics.pot_rejected_reason)


if __name__ == "__main__":
    unittest.main()
