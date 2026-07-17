"""Filesystem layout management for a JLPT notes repository."""

from dataclasses import asdict, replace
from datetime import date, timedelta
import json
from pathlib import Path
from uuid import uuid4

from .frontmatter import write_card
from .models import Card


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
        metadata_text, _ = text[4:].split("\n---\n\n", 1)
        metadata = json.loads(metadata_text)
        if metadata["confirmed"]:
            raise ValueError("draft has already been confirmed")
        proposal = dict(metadata["proposal"])
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
