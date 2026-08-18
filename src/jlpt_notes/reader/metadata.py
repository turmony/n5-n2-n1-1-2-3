"""Generic, non-mutating metadata parsing for reader source documents."""

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class DocumentMetadata:
    display_title: str
    level: str | None
    content_type: str
    source_id: str | None
    tags: tuple[str, ...]
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ParsedMarkdown:
    metadata: DocumentMetadata
    body: str
    warning: str | None = None


def parse_markdown(relative_path: Path, text: str) -> ParsedMarkdown:
    """Parse supported JSON frontmatter without changing the source text."""
    raw: dict[str, Any] = {}
    body = text
    warning = None
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        metadata_text, body = text[4:].split("\n---\n", 1)
        body = body.lstrip("\n")
        try:
            loaded = json.loads(metadata_text)
            raw = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            warning = "元数据无法解析；正文仍以只读方式显示。"

    proposal = raw.get("proposal") if isinstance(raw.get("proposal"), dict) else {}
    source_id = _first_text(raw.get("id"), proposal.get("id"))
    level = _first_text(raw.get("level"), proposal.get("level"), _level_from_path(relative_path))
    title = _first_text(raw.get("title"), proposal.get("title"), _first_heading(body), relative_path.stem)
    content_type = _content_type(relative_path, raw, proposal)
    display_title = _display_title(relative_path, source_id, level, title, content_type)
    tags_value = raw.get("tags", proposal.get("tags", []))
    tags = tuple(str(value) for value in tags_value) if isinstance(tags_value, list) else ()
    fields = _display_fields(raw, proposal, level, content_type, tags)
    return ParsedMarkdown(
        DocumentMetadata(display_title, level, content_type, source_id, tags, fields), body, warning
    )


def render_metadata_block(metadata: DocumentMetadata) -> str:
    """Render escaped document metadata for insertion into generated HTML."""
    chips = "".join(
        f'<span class="jlpt-meta-chip"><b>{escape(label)}</b> {escape(value)}</span>'
        for label, value in metadata.fields
    )
    return (
        f'<div class="jlpt-meta" aria-label="资料信息" '
        f'data-document-title="{escape(metadata.display_title)}">{chips}</div>'
        if chips
        else ""
    )


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _level_from_path(relative_path: Path) -> str | None:
    match = re.search(r"(?i)(?:^|[^a-z0-9])n([1-5])(?:$|[^a-z0-9])", relative_path.as_posix())
    return f"N{match.group(1)}" if match else None


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            heading = match.group(1).strip()
            heading = re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", heading)
            heading = re.sub(r"^N[1-5]\s+", "", heading, flags=re.IGNORECASE)
            return heading or None
    return None


def _content_type(relative_path: Path, raw: dict[str, Any], proposal: dict[str, Any]) -> str:
    path = relative_path.as_posix().lower()
    if "/drafts/" in f"/{path}" or path.startswith("drafts/"):
        return "draft"
    if "/quizzes/questions/" in f"/{path}" or path.startswith("quizzes/questions/"):
        return "quiz-question"
    if "/quizzes/results/" in f"/{path}" or path.startswith("quizzes/results/"):
        return "quiz-result"
    if "/reviews/" in f"/{path}" or path.startswith("reviews/"):
        return "review"
    if "/history/" in f"/{path}" or path.startswith("history/"):
        return "history"
    return _first_text(raw.get("kind"), proposal.get("kind")) or "document"


def _display_title(
    relative_path: Path,
    source_id: str | None,
    level: str | None,
    title: str | None,
    content_type: str,
) -> str:
    safe_title = title or relative_path.stem
    if content_type == "draft":
        return f"{source_id}｜草稿｜{safe_title}" if source_id else f"草稿｜{safe_title}"
    if source_id:
        return f"{source_id}｜{safe_title}"
    if content_type in {"quiz-result", "quiz-question", "review", "history"}:
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", relative_path.as_posix())
        pieces = [piece for piece in (level, date_match.group(0) if date_match else None, safe_title) if piece]
        return "｜".join(pieces)
    return f"{level}｜{safe_title}" if level else safe_title


def _display_fields(
    raw: dict[str, Any],
    proposal: dict[str, Any],
    level: str | None,
    content_type: str,
    tags: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    def value(name: str, *alternatives: str) -> str | None:
        return _first_text(
            raw.get(name), proposal.get(name), *(raw.get(key) for key in alternatives), *(proposal.get(key) for key in alternatives)
        )

    entries: list[tuple[str, str]] = []
    if level:
        entries.append(("等级", level))
    if content_type != "document":
        entries.append(("类型", content_type))
    status = value("status")
    if status:
        entries.append(("状态", status))
    if tags:
        entries.append(("标签", "、".join(tags)))
    for label, name, alternatives in (
        ("创建", "created_at", ("created",)),
        ("更新", "updated_at", ("updated",)),
        ("下次复习", "next_review", ()),
        ("来源", "source", ("source_url",)),
    ):
        field_value = value(name, *alternatives)
        if field_value:
            entries.append((label, field_value))
    return tuple(entries)
