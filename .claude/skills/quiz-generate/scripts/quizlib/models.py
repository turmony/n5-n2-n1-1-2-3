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


@dataclass
class QuestionCard:
    id: str
    path: str = ""
    frontmatter: dict = field(default_factory=dict)

    def _get(self, key, default=None):
        return self.frontmatter.get(key, default)

    @property
    def level(self): return self._get("level", "")
    @property
    def item_type(self): return self._get("item_type", "")
    @property
    def prompt(self): return self._get("prompt", "")
    @property
    def options(self): return self._get("options", {}) or {}
    @property
    def correct_option(self): return str(self._get("correct_option", "") or "")
    @property
    def translation(self): return self._get("translation", "")
    @property
    def tested_cards(self): return self._get("tested_cards", []) or []
    @property
    def recommended_order(self): return self._get("recommended_order", "")
    @property
    def conjugation(self): return self._get("conjugation", "")
    @property
    def correct_explanation(self): return self._get("correct_explanation", "")
