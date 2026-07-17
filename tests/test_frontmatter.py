import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.frontmatter import read_card, write_card
from jlpt_notes.models import Card
from jlpt_notes.repository import Repository


class FrontmatterTests(unittest.TestCase):
    def test_card_round_trips_as_structured_frontmatter(self) -> None:
        card = Card(
            id="N3-G-0001",
            kind="grammar",
            level="N3",
            title="～わけではない",
            body="# 核心用法\n并非……",
            status="confirmed",
            card_revision=1,
            schema_version=1,
            created_at=date(2026, 7, 17),
            updated_at=date(2026, 7, 17),
            next_review=date(2026, 7, 24),
            source={"teacher": "出口仁", "lesson": "12"},
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "card.md"
            write_card(path, card)
            self.assertEqual(read_card(path), card)

    def test_card_rejects_invalid_level(self) -> None:
        with self.assertRaisesRegex(ValueError, "level"):
            Card(
                id="N9-G-0001", kind="grammar", level="N9", title="x", body="x",
                status="confirmed", card_revision=1, schema_version=1,
                created_at=date.today(), updated_at=date.today(),
                next_review=date.today(), source={},
            )

    def test_repository_creates_all_required_directories(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "jlpt-notes"
            Repository(root).init_layout()
            self.assertTrue((root / "grammar").is_dir())
            self.assertTrue((root / "backups").is_dir())
