"""Filesystem layout management for a JLPT notes repository."""

from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .frontmatter import write_card
from .models import Card
from .quizzes import Question, QuizResult


class Repository:
    """Own the persistent directory layout for learner data."""

    REQUIRED_DIRECTORIES = (
        "grammar", "vocabulary", "reading", "drafts", "reviews", "quizzes",
        "analytics", "history", "schemas", "backups",
    )

    def __init__(self, root: Path) -> None:
        self.root = root

    def init_layout(self) -> None:
        """Create every required top-level directory."""
        for name in self.REQUIRED_DIRECTORIES:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def create_draft(self, raw_text: str, proposed_card: Card) -> Path:
        """Persist learner output and a proposed card without creating a study card."""
        self.init_layout()
        draft_id = f"draft-{uuid4().hex[:12]}"
        path = self.root / "drafts" / f"{draft_id}.md"
        proposal = asdict(proposed_card)
        for key in ("created_at", "updated_at", "next_review"):
            proposal[key] = proposal[key].isoformat()
        proposal["tags"] = list(proposal["tags"])
        proposal["confusions"] = list(proposal["confusions"])
        path.write_text(
            "---\n" + json.dumps({"draft_id": draft_id, "confirmed": False, "proposal": proposal}, ensure_ascii=False, indent=2)
            + "\n---\n\n## 学习者原始输出\n" + raw_text + "\n\n## 校对后的待确认卡\n" + proposed_card.title + "\n",
            encoding="utf-8",
        )
        return path

    def confirm_draft(self, draft_id: str, confirmed_on: date) -> Card:
        """Promote a draft to a confirmed card and begin its seven-day cycle."""
        path = self.root / "drafts" / f"{draft_id}.md"
        text = path.read_text(encoding="utf-8")
        metadata_text, body = text[4:].split("\n---\n\n", 1)
        metadata = json.loads(metadata_text)
        if metadata["confirmed"]:
            raise ValueError("draft has already been confirmed")
        proposal = dict(metadata["proposal"])
        proposal.setdefault("body", body.rstrip("\n"))
        for key in ("created_at", "updated_at", "next_review"):
            proposal[key] = date.fromisoformat(proposal[key])
        proposal["tags"] = tuple(proposal.get("tags", []))
        proposal["confusions"] = tuple(proposal.get("confusions", []))
        card = replace(Card(**proposal), created_at=confirmed_on, updated_at=confirmed_on,
                       next_review=confirmed_on + timedelta(days=7))
        destination = self.root / ("grammar" if card.kind == "grammar" else "vocabulary") / card.level.lower() / f"{card.id}.md"
        write_card(destination, card)
        metadata["confirmed"] = True
        path.write_text("---\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n---\n\n" + text.split("\n---\n\n", 1)[1], encoding="utf-8")
        events = self.root / "reviews" / "events.jsonl"
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event_type": "confirmed", "card_id": card.id, "date": confirmed_on.isoformat()}, ensure_ascii=False) + "\n")
        return card

    def save_question(self, question: Question) -> Path:
        self.init_layout()
        path = self.root / "quizzes" / "questions" / f"{question.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = question.__dict__
        path.write_text("---\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n---\n\n" + question.prompt + "\n", encoding="utf-8")
        return path

    def record_attempt(self, question: Question, result: QuizResult, answered_on: date, error_tags: tuple[str, ...]) -> dict:
        self.init_layout()
        event = {"question_id": question.id, "revision": question.revision, "item_type": question.item_type,
                 "selected_option": result.selected_option, "is_correct": result.is_correct, "uncertain": result.uncertain,
                 "error_tags": list(error_tags), "date": answered_on.isoformat()}
        with (self.root / "quizzes" / "attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def create_vocab_candidate(self, question: Question, attempt: dict) -> Path:
        if attempt["is_correct"] or question.item_type not in {"kanji_reading", "orthography", "word_formation", "context_expression", "paraphrase", "usage"}:
            raise ValueError("only incorrect vocabulary attempts create candidates")
        folder = self.root / "drafts" / "vocabulary-candidates"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"candidate-{uuid4().hex[:12]}.md"
        path.write_text("# 待确认词汇卡\n\n- 来源题目：" + question.id + "\n- 错误选项：" + attempt["selected_option"] + "\n\n" + question.prompt + "\n", encoding="utf-8")
        return path

    def create_backup(self, on_date: date) -> Path:
        self.init_layout()
        archive = self.root / "backups" / f"{on_date.isoformat()}-jlpt-notes.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED) as backup:
            for path in self.root.rglob("*"):
                if path.is_file() and "backups" not in path.parts and ".git" not in path.parts and "__pycache__" not in path.parts:
                    backup.write(path, path.relative_to(self.root).as_posix())
        return archive
