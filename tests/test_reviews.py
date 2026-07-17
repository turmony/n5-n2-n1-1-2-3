import unittest
from datetime import date

from jlpt_notes.models import Card
from jlpt_notes.reviews import complete_review, due_cards


def card(card_id: str, next_review: date) -> Card:
    return Card(card_id, "grammar", "N3", card_id, "内容", "confirmed", 1, 1,
                date(2026, 7, 1), date(2026, 7, 1), next_review, {})


class ReviewTests(unittest.TestCase):
    def test_late_completion_restarts_seven_day_cycle(self) -> None:
        self.assertEqual(date(2026, 7, 17), complete_review(card("N3-G-0001", date(2026, 7, 8)), date(2026, 7, 10)).next_review)

    def test_daily_queue_prioritises_overdue_and_respects_limit(self) -> None:
        queue = due_cards([card("N3-G-0001", date(2026, 7, 15)), card("N2-G-0001", date(2026, 7, 10)), card("N3-G-0002", date(2026, 7, 17))], date(2026, 7, 17), 2)
        self.assertEqual(["N2-G-0001", "N3-G-0001"], [item.id for item in queue.selected])
        self.assertEqual(1, queue.not_selected_count)
