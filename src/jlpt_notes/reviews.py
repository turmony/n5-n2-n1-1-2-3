"""Fixed seven-day review scheduling."""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable

from .models import Card


@dataclass(frozen=True)
class DailyQueue:
    selected: tuple[Card, ...]
    due_count: int
    overdue_count: int
    not_selected_count: int


def due_cards(cards: Iterable[Card], on_date: date, limit: int) -> DailyQueue:
    """Choose due cards, always putting the most overdue cards first."""
    if limit < 0:
        raise ValueError("limit must be non-negative")
    due = [item for item in cards if item.next_review <= on_date]
    due.sort(key=lambda item: (item.next_review, item.id))
    selected = tuple(due[:limit])
    return DailyQueue(selected, len(due), sum(item.next_review < on_date for item in due), len(due) - len(selected))


def complete_review(card: Card, completed_on: date) -> Card:
    """Advance only from the actual completion date, never from the old due date."""
    return replace(card, updated_at=completed_on, next_review=completed_on + timedelta(days=7))
