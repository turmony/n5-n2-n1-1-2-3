"""Original N2 question validation and answer feedback."""

from dataclasses import dataclass

from .n2_taxonomy import ITEM_TYPES


@dataclass(frozen=True)
class Question:
    id: str
    revision: int
    level: str
    item_type: str
    prompt: str
    options: dict[str, str]
    correct_option: str
    correct_explanation: str
    option_explanations: dict[str, str]

    def __post_init__(self) -> None:
        if self.item_type not in ITEM_TYPES:
            raise ValueError("item type must be a supported N2 non-listening type")
        if set(self.options) != {"1", "2", "3", "4"} or self.correct_option not in self.options:
            raise ValueError("question requires exactly four options")
        if set(self.option_explanations) != set(self.options) - {self.correct_option}:
            raise ValueError("three distractor explanations are required")


@dataclass(frozen=True)
class QuizResult:
    is_correct: bool
    correct_explanation: str
    distractor_explanations: dict[str, str]
    selected_option: str
    uncertain: bool


def score(question: Question, selected_option: str, uncertain: bool = False) -> QuizResult:
    """Score an answer while retaining all explanatory feedback."""
    if selected_option not in question.options:
        raise ValueError("selected option must be 1 through 4")
    return QuizResult(selected_option == question.correct_option, question.correct_explanation,
                      question.option_explanations, selected_option, uncertain)
