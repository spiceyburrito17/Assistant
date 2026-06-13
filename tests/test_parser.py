import unittest

from torn_accessibility_hud.config import ParserConfig
from torn_accessibility_hud.models import ActionType, OCRLine, Street
from torn_accessibility_hud.parsing.cards import parse_cards
from torn_accessibility_hud.parsing.log_parser import ActionLogParser


class ParserTests(unittest.TestCase):
    def test_parse_cards_normalizes_ten_and_suits(self) -> None:
        self.assertEqual(parse_cards("Your hand: 10 hearts A spades"), ("Th", "As"))

    def test_hero_cards_are_validated(self) -> None:
        parser = ActionLogParser()
        event = parser.parse_line(OCRLine("You were dealt As Kd", 0.93))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.action, ActionType.DEALT_HERO)
        self.assertEqual(event.cards, ("As", "Kd"))

    def test_low_confidence_line_is_dropped(self) -> None:
        parser = ActionLogParser(ParserConfig(min_line_confidence=0.8))
        self.assertIsNone(parser.parse_line(OCRLine("Villain raises to 500", 0.4)))

    def test_unreasonable_amount_is_dropped(self) -> None:
        parser = ActionLogParser(ParserConfig(max_reasonable_amount=1000))
        self.assertIsNone(parser.parse_line(OCRLine("Villain raises to 99999999", 0.99)))

    def test_player_action_is_normalized(self) -> None:
        parser = ActionLogParser()
        event = parser.parse_line(OCRLine("QuickFox raises to 1,250", 0.95))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.player_name, "QuickFox")
        self.assertEqual(event.action, ActionType.RAISE)
        self.assertEqual(event.amount, 1250.0)

    def test_board_street_is_detected(self) -> None:
        parser = ActionLogParser()
        event = parser.parse_line(OCRLine("Flop: As Kd 2c", 0.96))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.street, Street.FLOP)
        self.assertEqual(event.cards, ("As", "Kd", "2c"))

    def test_pot_amount_keeps_literal_three_digit_values(self) -> None:
        parser = ActionLogParser()
        event = parser.parse_line(OCRLine("POT: 545", 0.94))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.action, ActionType.POT)
        self.assertEqual(event.amount, 545.0)

    def test_pot_amount_corrects_misread_dollar_prefix(self) -> None:
        parser = ActionLogParser()
        event = parser.parse_line(OCRLine("POT: 5660", 0.94))
        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.action, ActionType.POT)
        self.assertEqual(event.amount, 660.0)


if __name__ == "__main__":
    unittest.main()
