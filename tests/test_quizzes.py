import unittest

from jlpt_notes.quizzes import Question, score


class QuizTests(unittest.TestCase):
    def test_scoring_returns_three_distractor_explanations(self) -> None:
        question = Question("N2-Q-0001", 1, "N2", "grammar_form", "题干", {"1": "A", "2": "B", "3": "C", "4": "D"}, "2", "B 正确", {"1": "A 错", "3": "C 错", "4": "D 错"})
        result = score(question, "3", True)
        self.assertFalse(result.is_correct)
        self.assertEqual("B 正确", result.correct_explanation)
        self.assertEqual(3, len(result.distractor_explanations))

    def test_listening_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-listening"):
            Question("N2-Q-0002", 1, "N2", "quick_response", "题干", {"1": "A", "2": "B", "3": "C", "4": "D"}, "1", "A", {"2": "x", "3": "x", "4": "x"})

    def test_non_listening_type_accepts_levels_from_n5_through_n1(self) -> None:
        for level in ("N5", "N4", "N3", "N2", "N1"):
            question = Question(
                f"{level}-Q-0001", 1, level, "grammar_form", "题干",
                {"1": "A", "2": "B", "3": "C", "4": "D"},
                "1", "A 正确", {"2": "B 错", "3": "C 错", "4": "D 错"},
            )
            self.assertEqual(level, question.level)

    def test_question_rejects_level_outside_n5_through_n1(self) -> None:
        with self.assertRaisesRegex(ValueError, "N5, N4, N3, N2, N1"):
            Question(
                "N9-Q-0001", 1, "N9", "grammar_form", "题干",
                {"1": "A", "2": "B", "3": "C", "4": "D"},
                "1", "A 正确", {"2": "B 错", "3": "C 错", "4": "D 错"},
            )
