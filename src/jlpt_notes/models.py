"""Domain models for persistent JLPT learning data."""

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Literal


LEVELS = frozenset({"N5", "N4", "N3", "N2", "N1"})
CARD_ID_PATTERN = re.compile(r"^N[1-5]-(G|V)-\d{4,}$")


@dataclass(frozen=True)
class Card:
    id: str
    kind: Literal["grammar", "vocabulary"]
    level: str
    title: str
    body: str
    status: Literal["confirmed"]
    card_revision: int
    schema_version: int
    created_at: date
    updated_at: date
    next_review: date
    source: dict[str, str]
    tags: tuple[str, ...] = field(default_factory=tuple)
    confusions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError("level must be one of N5, N4, N3, N2, N1")
        if self.kind not in {"grammar", "vocabulary"}:
            raise ValueError("kind must be grammar or vocabulary")
        if not CARD_ID_PATTERN.fullmatch(self.id):
            raise ValueError("id has an invalid format")
        if self.card_revision < 1 or self.schema_version < 1:
            raise ValueError("revisions must be positive")
