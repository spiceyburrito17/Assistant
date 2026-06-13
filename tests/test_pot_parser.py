import unittest

from torn_accessibility_hud.models import GameSnapshot, PotOCRResult, TableOCRResult
from torn_accessibility_hud.parsing.pot_parser import parse_pot_region_text, parse_pot_text, parse_pot_text_detailed
from torn_accessibility_hud.parsing.pot_sanity import validate_pot_update
from torn_accessibility_hud.state import TrustedTableStateManager


class PotParserTests(unittest.TestCase):
    def test_pot_dollar_540(self) -> None:
        amount, status = parse_pot_text("POT: $540")
        self.assertEqual(amount, 540.0)
        self.assertEqual(status, "ok")

    def test_misread_dollar_as_leading_five(self) -> None:
        amount, status = parse_pot_text("POT: 5540")
        self.assertEqual(amount, 540.0)
        self.assertEqual(status, "leading_5_as_dollar")

    def test_plain_540_without_dollar(self) -> None:
        amount, status = parse_pot_text("POT: 540")
        self.assertEqual(amount, 540.0)
        self.assertEqual(status, "ok")

    def test_comma_formatted_pot(self) -> None:
        amount, status = parse_pot_text("POT: $2,400")
        self.assertEqual(amount, 2400.0)
        self.assertEqual(status, "ok")

    def test_ignores_junk_after_first_token(self) -> None:
        result = parse_pot_text_detailed("POT: $2,4008281400")
        self.assertEqual(result.candidate, "$2,400")
        self.assertEqual(result.normalized, 2400.0)

    def test_middle_four_correction(self) -> None:
        amount, status = parse_pot_text("POT: 545")
        self.assertEqual(amount, 55.0)
        self.assertEqual(status, "middle_4_as_dollar")

    def test_keeps_normal_three_digit_pot(self) -> None:
        amount, status = parse_pot_text("POT: 675")
        self.assertEqual(amount, 675.0)
        self.assertEqual(status, "ok")

    def test_pot_region_fallback_without_label(self) -> None:
        result = parse_pot_region_text("5540")
        self.assertEqual(result.normalized, 540.0)


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
                    pot_candidate="$540",
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
                    pot_candidate="$2,400",
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
