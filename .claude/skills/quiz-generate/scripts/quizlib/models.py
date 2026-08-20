from dataclasses import dataclass, field

ERROR = "error"
WARN = "warn"


@dataclass
class Finding:
    check: str        # "C1".."C7"
    severity: str     # ERROR / WARN
    location: str     # 如 "题21 / N4-Q-0302"
    message: str


@dataclass
class PaperQuestion:
    number: int
    section: str                 # "form" | "order" | "cloze"
    stem: str = ""
    options: dict = field(default_factory=dict)
    star_pos: int | None = None  # 排序题★在第几空（1 起）


@dataclass
class Paper:
    questions: list = field(default_factory=list)
    raw_text: str = ""


@dataclass
class AnswerEntry:
    number: int
    card_id: str = ""
    stem: str = ""
    grammar_ids: list = field(default_factory=list)
    correct_option: str = ""
    order: str | None = None
    analysis: str = ""
    option_analyses: dict = field(default_factory=dict)
    translation: str = ""
    conjugation: str = ""
