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
    frontmatter = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if frontmatter:
        metadata_text = frontmatter.group(1)
        body = text[frontmatter.end() :].lstrip("\r\n")
        try:
            loaded = json.loads(metadata_text)
            if not isinstance(loaded, dict):
                raise ValueError("frontmatter must be an object")
            raw = loaded
        except json.JSONDecodeError:
            warning = "元数据无法解析；正文仍以只读方式显示。"
        except ValueError:
            warning = "元数据无法解析；正文仍以只读方式显示。"

    proposal = raw.get("proposal") if isinstance(raw.get("proposal"), dict) else {}
    source_id = _first_text(raw.get("id"), proposal.get("id"), _id_from_path(relative_path))
    level = _first_text(raw.get("level"), proposal.get("level"), _level_from_path(relative_path))
    content_type = _content_type(relative_path, raw, proposal)
    domain_title = raw.get("prompt") if content_type == "quiz-question" else None
    title = _catalog_title(
        _first_text(
            raw.get("title"),
            proposal.get("title"),
            domain_title,
            _first_heading(body),
            relative_path.stem,
        )
    )
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


def _id_from_path(relative_path: Path) -> str | None:
    match = re.match(r"(?i)(N[1-5]-[A-Z]+-\d+)(?:$|[-_.])", relative_path.stem)
    return match.group(1).upper() if match else None


def _catalog_title(value: str | None, limit: int = 80) -> str | None:
    if value is None:
        return None
    # Collapse layout whitespace while preserving Japanese ideographic spaces,
    # which quiz prompts use as meaningful answer blanks such as ``（　）``.
    normalized = re.sub(r"[ \t\r\n\f\v]+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


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
    explicit_type = _first_text(raw.get("kind"), proposal.get("kind"))
    if explicit_type:
        return explicit_type
    if "/grammar/" in f"/{path}" or path.startswith("grammar/"):
        return "grammar"
    return "document"


def _display_title(
    relative_path: Path,
    source_id: str | None,
    level: str | None,
    title: str | None,
    content_type: str,
) -> str:
    safe_title = title or relative_path.stem
    if content_type == "draft":
        if source_id:
            title_without_id = _remove_leading_identity(safe_title, source_id)
            return f"{source_id}｜草稿｜{title_without_id or safe_title}"
        return f"草稿｜{safe_title}"
    if source_id:
        if _has_leading_identity(safe_title, source_id):
            return safe_title
        return f"{source_id}｜{safe_title}"
    if content_type in {"quiz-result", "quiz-question", "review", "history"}:
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", relative_path.as_posix())
        pieces = []
        for piece in (level, date_match.group(0) if date_match else None):
            if piece and not _has_leading_identity(safe_title, piece):
                pieces.append(piece)
        pieces.append(safe_title)
        return "｜".join(pieces)
    return (
        f"{level}｜{safe_title}"
        if level and not _has_leading_identity(safe_title, level)
        else safe_title
    )


def _has_leading_identity(title: str, identity: str) -> bool:
    return bool(
        re.match(
            rf"^{re.escape(identity)}(?=$|[\s｜|:：\-—])",
            title,
            flags=re.IGNORECASE,
        )
    )


def _remove_leading_identity(title: str, identity: str) -> str:
    return re.sub(
        rf"^{re.escape(identity)}(?:\s*[｜|:：\-—]\s*|\s+)",
        "",
        title,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _display_fields(
    raw: dict[str, Any],
    proposal: dict[str, Any],
    level: str | None,
    content_type: str,
    tags: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    def value(name: str, *alternatives: str) -> str | None:
        candidates = [raw.get(name), proposal.get(name)]
        for key in alternatives:
            candidates.extend((raw.get(key), proposal.get(key)))
        for candidate in candidates:
            rendered = _display_metadata_value(candidate)
            if rendered:
                return rendered
        return None

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


def _display_metadata_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if value is None:
        return None
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        parts = []
        for key in sorted(value, key=lambda item: (str(item).casefold(), str(item))):
            rendered = _display_metadata_value(value[key])
            if rendered:
                parts.append(f"{key}: {rendered}")
        return "；".join(parts) or None
    if isinstance(value, list):
        parts = [
            rendered
            for item in value
            if (rendered := _display_metadata_value(item)) is not None
        ]
        return "、".join(parts) or None
    return str(value)
