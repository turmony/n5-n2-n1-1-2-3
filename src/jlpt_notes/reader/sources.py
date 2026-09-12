"""Read-only discovery and catalog generation for LAN reader sources."""

from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote

from .metadata import DocumentMetadata, ParsedMarkdown, parse_markdown


_SUMMARY_FIELDS = (
    "id",
    "question_id",
    "card_id",
    "draft_id",
    "revision",
    "item_type",
    "selected_option",
    "is_correct",
    "uncertain",
    "date",
    "created_at",
    "completed_at",
    "level",
    "kind",
    "result",
    "status",
    "score",
    "correct",
)


@dataclass(frozen=True)
class SourcePage:
    """A source document prepared for rendering without changing its file."""

    relative_path: Path
    output_path: Path
    markdown: str
    metadata: DocumentMetadata
    content_hash: str
    warning: str | None = None


def load_source_pages(root: Path) -> tuple[SourcePage, ...]:
    """Return every visible Markdown or JSONL source below *root* read-only."""
    resolved_root = root.resolve(strict=True)
    pages: list[SourcePage] = []
    for path in iter_supported_visible_source_files(resolved_root):
        resolved_path = _resolved_below(path, resolved_root)
        if resolved_path is None or path.is_symlink():
            continue
        relative_path = path.relative_to(resolved_root)
        content = resolved_path.read_bytes()
        text = content.decode("utf-8")
        if path.suffix.lower() == ".jsonl":
            parsed = _parse_jsonl(relative_path, text)
            output_path = relative_path.with_suffix(relative_path.suffix + ".md")
        else:
            parsed = parse_markdown(relative_path, text)
            output_path = relative_path
        pages.append(
            SourcePage(
                relative_path=relative_path,
                output_path=output_path,
                markdown=parsed.body,
                metadata=parsed.metadata,
                content_hash=sha256(content).hexdigest(),
                warning=parsed.warning,
            )
        )
    return tuple(sorted(pages, key=lambda page: _path_sort_key(page.relative_path)))


def build_catalog_page(pages: tuple[SourcePage, ...]) -> SourcePage:
    """Create the generated root catalog used for navigation and filtering."""
    entries = "\n".join(_catalog_entry(page) for page in sorted(pages, key=_catalog_sort_key))
    markdown = "\n".join(
        (
            "# JLPT 学习资料库",
            "",
            "<p class=\"jlpt-catalog-intro\">仅在本机局域网内以只读方式浏览。</p>",
            "",
            '<ul class="jlpt-catalog" data-reader-catalog>',
            entries,
            "</ul>",
            "",
        )
    )
    metadata = DocumentMetadata(
        display_title="JLPT 学习资料库",
        level=None,
        content_type="catalog",
        source_id=None,
        tags=(),
        fields=(),
    )
    return SourcePage(
        relative_path=Path("index.md"),
        output_path=Path("index.md"),
        markdown=markdown,
        metadata=metadata,
        content_hash=sha256(markdown.encode("utf-8")).hexdigest(),
    )


def iter_supported_visible_source_files(
    root: Path, *, suffixes: frozenset[str] = frozenset({".md", ".jsonl"})
) -> tuple[Path, ...]:
    """Return visible files of the requested types, defaulting to documents.

    Files are eligible when they are non-symlink regular files below *root*,
    have a requested suffix, and have no hidden path component. Rendering and
    polling share this traversal for both documents and raster assets.
    """
    resolved_root = root.resolve(strict=True)
    paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(resolved_root, followlinks=False):
        current = Path(directory)
        if _resolved_below_or_same(current, resolved_root) is None:
            directory_names[:] = []
            continue
        directory_names[:] = sorted(
            (
                name
                for name in directory_names
                if not name.startswith(".")
                and not _is_directory_link(current / name)
                and _resolved_below(current / name, resolved_root) is not None
            ),
            key=lambda name: (name.casefold(), name),
        )
        for name in sorted(file_names, key=lambda name: (name.casefold(), name)):
            path = current / name
            if name.startswith(".") or path.is_symlink() or path.suffix.lower() not in suffixes:
                continue
            if path.is_file() and _resolved_below(path, resolved_root) is not None:
                paths.append(path)
    return tuple(paths)


def iter_visible_images(root: Path) -> tuple[Path, ...]:
    """Discover raster assets using the same containment and visibility rules."""
    return iter_supported_visible_source_files(
        root, suffixes=frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
    )


def _is_directory_link(path: Path) -> bool:
    """Reject symlink, junction, and other reparse-point directories."""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _resolved_below(path: Path, root: Path) -> Path | None:
    resolved = _resolved_below_or_same(path, root)
    return resolved if resolved is not None and resolved != root else None


def _resolved_below_or_same(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _parse_jsonl(relative_path: Path, text: str) -> ParsedMarkdown:
    rendered_lines = [f"# {relative_path.stem}", ""]
    warnings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            warning = f"第 {line_number} 行无法解析，已跳过。"
            warnings.append(warning)
            rendered_lines.extend((f"> ⚠️ {warning}", ""))
            continue
        formatted = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True)
        rendered_lines.extend(
            (
                *_render_json_summary(record),
                '<details class="jlpt-json-record">',
                f"<summary>记录 {line_number}</summary>",
                f"<pre>{escape(formatted)}</pre>",
                "</details>",
                "",
            )
        )
    body = "\n".join(rendered_lines)
    parsed = parse_markdown(relative_path, body)
    return ParsedMarkdown(parsed.metadata, parsed.body, " ".join(warnings) or None)


def _render_json_summary(record: object) -> tuple[str, ...]:
    if not isinstance(record, dict):
        return ()
    fields = tuple(
        (field, record[field])
        for field in _SUMMARY_FIELDS
        if field in record
        if record[field] is None or isinstance(record[field], (str, int, float, bool))
    )
    if not fields:
        return ()
    lines = ['<dl class="jlpt-json-summary">']
    for field, value in fields:
        lines.append(f"<dt>{escape(field)}</dt><dd>{escape(_display_json_scalar(value))}</dd>")
    lines.extend(("</dl>", ""))
    return tuple(lines)


def _display_json_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _catalog_entry(page: SourcePage) -> str:
    metadata = page.metadata
    level = metadata.level or ""
    content_type = metadata.content_type
    tags = " ".join(metadata.tags)
    link = quote(page.output_path.as_posix(), safe="/")
    return (
        f'<li class="jlpt-catalog-entry" data-level="{escape(level, quote=True)}" '
        f'data-type="{escape(content_type, quote=True)}" '
        f'data-tags="{escape(tags, quote=True)}">'
        f'<a href="{link}">{escape(metadata.display_title)}</a>'
        f'<span class="jlpt-catalog-path">{escape(page.relative_path.as_posix())}</span>'
        "</li>"
    )


def _catalog_sort_key(page: SourcePage) -> tuple[object, ...]:
    source_id = page.metadata.source_id or ""
    identifier = re.fullmatch(r"N([1-5])-([A-Z]+)-(\d+)", source_id, re.IGNORECASE)
    path = _path_sort_key(page.relative_path)
    if identifier:
        return (0, int(identifier.group(1)), identifier.group(2).casefold(), int(identifier.group(3)), *path)
    date = _date_for_report(page)
    if date:
        return (1, page.metadata.content_type.casefold(), -int(date.replace("-", "")), *path)
    return (2, *path)


def _date_for_report(page: SourcePage) -> str | None:
    if page.metadata.content_type not in {"quiz-question", "quiz-result", "review", "history"}:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", page.relative_path.as_posix())
    return match.group(0) if match else None


def _path_sort_key(path: Path) -> tuple[str, str]:
    value = path.as_posix()
    return (value.casefold(), value)
