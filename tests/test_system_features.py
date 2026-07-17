import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.analytics import aggregate_attempts, render_daily_report
from jlpt_notes.quizzes import Question, score
from jlpt_notes.repository import Repository


def vocabulary_question() -> Question:
    return Question("N2-Q-0003", 1, "N2", "usage", "彼は（　）をよく使う。",
                    {"1": "言葉", "2": "言葉を", "3": "言葉に", "4": "言葉で"}, "2", "をが必要。",
                    {"1": "助詞がない。", "3": "にではない。", "4": "でではない。"})


class SystemFeatureTests(unittest.TestCase):
    def test_question_attempt_is_saved_and_wrong_vocab_creates_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "notes")
            question = vocabulary_question()
            repo.save_question(question)
            attempt = repo.record_attempt(question, score(question, "3", True), date(2026, 7, 17), ("usage",))
            candidate = repo.create_vocab_candidate(question, attempt)
            self.assertTrue((repo.root / "quizzes" / "questions" / "N2-Q-0003.md").exists())
            self.assertTrue(candidate.exists())

    def test_daily_report_and_backup_are_readable(self) -> None:
        with TemporaryDirectory() as directory:
            repo = Repository(Path(directory) / "notes")
            repo.init_layout()
            report = render_daily_report(aggregate_attempts([]), 0, 0, 0, 10)
            self.assertIn("今日复习", report)
            self.assertTrue(repo.create_backup(date(2026, 7, 17)).exists())
