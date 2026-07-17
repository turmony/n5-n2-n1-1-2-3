import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.models import Card
from jlpt_notes.repository import Repository


def sample_card() -> Card:
    return Card("N3-G-0001", "grammar", "N3", "～わけではない", "内容", "confirmed", 1, 1,
                date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 8), {"teacher": "出口仁"})


class RepositoryTests(unittest.TestCase):
    def test_confirm_draft_preserves_original_and_sets_first_review(self) -> None:
        with TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "notes")
            draft = repo.create_draft("我的理解：并非全部否定。", sample_card())
            card = repo.confirm_draft(draft.stem, date(2026, 7, 17))
            self.assertIn("我的理解：并非全部否定。", draft.read_text(encoding="utf-8"))
            self.assertEqual(date(2026, 7, 24), card.next_review)
            self.assertTrue((repo.root / "grammar" / "n3" / "N3-G-0001.md").exists())
