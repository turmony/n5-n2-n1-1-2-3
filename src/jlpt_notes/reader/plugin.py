"""MkDocs integration for the read-only JLPT LAN reader."""

from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

import bleach
from mkdocs import plugins
from mkdocs.config import base, config_options as c
from mkdocs.structure.files import File, Files
from pymdownx.slugs import slugify

from .metadata import render_metadata_block
from .sources import SourcePage, build_catalog_page, load_source_pages


class ReaderPluginConfig(base.Config):
    """Configuration for the reader's packaged presentation assets."""

    assets_dir = c.Type(str, default="assets")


class JlptReaderPlugin(plugins.BasePlugin[ReaderPluginConfig]):
    """Expose a read-only source tree as generated MkDocs pages."""

    def on_config(self, config, **kwargs: Any):
        config["mdx_configs"].setdefault("toc", {}).setdefault("slugify", slugify())
        self._source_root = Path(config.docs_dir).resolve(strict=True)
        self._config_root = Path(config.config_file_path).resolve().parent
        self._pages = load_source_pages(self._source_root)
        self._pages_by_uri: dict[str, SourcePage] = {}
        self._files_by_relative_path: dict[Path, File] = {}
        self._url_hashes: dict[str, str] = {}
        return config

    def on_files(self, files: Files, config, **kwargs: Any) -> Files:
        virtual: list[File] = []
        for source in self._pages:
            file = File(
                _virtual_source_path(source).as_posix(),
                str(self._source_root),
                config.site_dir,
                config.use_directory_urls,
            )
            file.content_string = source.markdown
            self._pages_by_uri[file.src_uri] = source
            self._files_by_relative_path[source.relative_path] = file
            virtual.append(file)
        catalog = build_catalog_page(self._pages)
        catalog = SourcePage(
            relative_path=catalog.relative_path,
            output_path=catalog.output_path,
            markdown=_catalog_with_final_urls(catalog.markdown, self._files_by_relative_path),
            metadata=catalog.metadata,
            content_hash=catalog.content_hash,
            warning=catalog.warning,
        )
        catalog_file = File(
            "index.md",
            str(self._source_root),
            config.site_dir,
            config.use_directory_urls,
        )
        catalog_file.content_string = catalog.markdown
        self._pages_by_uri[catalog_file.src_uri] = catalog
        virtual.insert(0, catalog_file)
        for name in ("reader.css", "reader.js"):
            source_path = self._config_root / self.config.assets_dir / name
            file = File(
                f"assets/{name}",
                str(self._source_root),
                config.site_dir,
                config.use_directory_urls,
            )
            file.content_bytes = source_path.read_bytes()
            virtual.append(file)
        return Files(virtual)

    def on_nav(self, nav, config, files, **kwargs: Any):
        for page in nav.pages:
            source = self._pages_by_uri.get(page.file.src_uri)
            if source is not None:
                page.title = source.metadata.display_title
        _localize_and_sort_navigation(nav.items, self._pages_by_uri)
        return nav

    def on_page_markdown(self, markdown: str, page, **kwargs: Any) -> str:
        source = self._pages_by_uri[page.file.src_uri]
        page.title = source.metadata.display_title
        page.meta.update(
            {
                "reader_level": source.metadata.level or "",
                "reader_type": source.metadata.content_type,
            }
        )
        warning = f'!!! warning "读取提示"\n    {source.warning}\n\n' if source.warning else ""
        body = _demote_headings(markdown)
        safe_title = escape(source.metadata.display_title)
        return f"# {safe_title}\n\n{render_metadata_block(source.metadata)}\n\n{warning}{body}"

    def on_page_content(self, html: str, page, **kwargs: Any) -> str:
        """Keep generated page HTML readable while removing unsafe source HTML."""
        return _sanitize_html(html)

    def on_page_context(self, context, page, config, nav, **kwargs: Any):
        source = self._pages_by_uri.get(page.file.src_uri)
        if source is not None:
            self._url_hashes[page.file.url] = source.content_hash
        return context

    def on_post_build(self, config, **kwargs: Any) -> None:
        ordered = sorted(self._url_hashes.items())
        version_source = "".join(f"{url}\0{content_hash}\n" for url, content_hash in ordered)
        manifest = {
            "version": sha256(version_source.encode("utf-8")).hexdigest(),
            "pages": dict(ordered),
        }
        (Path(config.site_dir) / "reader-version.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )


def _demote_headings(markdown: str) -> str:
    """Reserve H1 for the generated display title without rewriting code samples."""
    output: list[str] = []
    lines = markdown.splitlines(keepends=True)
    in_fence: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            marker = fence.group(1)
            if in_fence is None:
                in_fence = marker[0]
            elif marker[0] == in_fence:
                in_fence = None
            output.append(line)
            index += 1
            continue
        if in_fence or re.match(r"^(?: {4}|\t)", line):
            output.append(line)
            index += 1
            continue

        if _is_setext_h1(lines, index):
            output.append(_setext_to_atx_h2(line))
            index += 2
            continue

        line = re.sub(
            r"^(\s{0,3}(?:>\s*)?)(#{1,5})(?=\s)",
            lambda match: match.group(1) + "#" + match.group(2),
            line,
        )
        line = re.sub(r"<(/?)h1\b", r"<\1h2", line, flags=re.IGNORECASE)
        output.append(line)
        index += 1
    return "".join(output)


def _is_setext_h1(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    current = lines[index]
    underline = lines[index + 1]
    return bool(
        current.strip()
        and not re.match(r"^\s{0,3}(?:>|#{1,6}|[-+*]\s|\d+[.)]\s)", current)
        and re.match(r"^\s{0,3}=+\s*(?:\r?\n)?$", underline)
    )


def _setext_to_atx_h2(line: str) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    return "## " + line.rstrip("\r\n").lstrip() + newline


def _virtual_source_path(source: SourcePage) -> Path:
    """Return a collision-proof virtual Markdown path for one source file."""
    source_kind = "jsonl" if source.relative_path.suffix.lower() == ".jsonl" else "markdown"
    name = f"{source.relative_path.name}.__reader_{source_kind}__.md"
    return Path("library") / source.relative_path.parent / name


def _catalog_with_final_urls(markdown: str, files: dict[Path, File]) -> str:
    """Replace catalog source links with the final route assigned by MkDocs files."""
    rewritten = markdown
    for relative_path, file in files.items():
        escaped_path = escape(relative_path.as_posix())
        pattern = (
            r'(<li class="jlpt-catalog-entry"[^>]*><a href=")[^"]+("[^>]*>.*?'
            + re.escape(f'<span class="jlpt-catalog-path">{escaped_path}</span>')
            + r"</li>)"
        )
        rewritten, replacements = re.subn(
            pattern,
            lambda match: match.group(1) + quote(file.url, safe="/%") + match.group(2),
            rewritten,
            count=1,
        )
        if replacements != 1:
            raise ValueError(f"Could not assign a virtual URL for {relative_path.as_posix()}")
    return rewritten


_FOLDER_LABELS = {
    "library": "资料库",
    "grammar": "正式语法卡",
    "drafts": "草稿",
    "quizzes": "测试",
    "reviews": "复习记录",
    "history": "修改历史",
}
_FOLDER_ORDER = {name: index for index, name in enumerate(_FOLDER_LABELS)}


def _localize_and_sort_navigation(items, pages_by_uri: dict[str, SourcePage]) -> None:
    """Keep the physical tree while using learner-facing labels and deterministic order."""
    for item in items:
        children = getattr(item, "children", None)
        if children is not None:
            _localize_and_sort_navigation(children, pages_by_uri)
            item.title = _FOLDER_LABELS.get(str(item.title).casefold(), item.title)
            children.sort(key=lambda child: _navigation_item_key(child, pages_by_uri))
    items.sort(key=lambda item: _navigation_item_key(item, pages_by_uri))


def _navigation_item_key(item, pages_by_uri: dict[str, SourcePage]) -> tuple[object, ...]:
    source = pages_by_uri.get(getattr(getattr(item, "file", None), "src_uri", ""))
    if source is not None:
        if source.metadata.content_type == "catalog":
            return (-1,)
        return (1, *_source_navigation_key(source))
    title = str(getattr(item, "title", ""))
    folder_name = title.casefold()
    original_folder_name = next(
        (name for name, label in _FOLDER_LABELS.items() if label == title), folder_name
    )
    return (0, _FOLDER_ORDER.get(original_folder_name, len(_FOLDER_ORDER)), folder_name)


def _source_navigation_key(source: SourcePage) -> tuple[object, ...]:
    source_id = source.metadata.source_id or ""
    structured = re.fullmatch(r"N([1-5])-([A-Z]+)-(\d+)", source_id, re.IGNORECASE)
    relative = source.relative_path.as_posix()
    if structured:
        return (0, int(structured.group(1)), structured.group(2).casefold(), int(structured.group(3)), relative.casefold(), relative)
    is_dated = source.metadata.content_type in {"quiz-question", "quiz-result", "review", "history"}
    date = re.search(r"\d{4}-\d{2}-\d{2}", relative)
    if is_dated and date:
        return (1, -int(date.group(0).replace("-", "")), relative.casefold(), relative)
    return (2, relative.casefold(), relative)


_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "code",
        "dd",
        "del",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "kbd",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "summary",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


def _allowed_attribute(tag: str, name: str, value: str) -> bool:
    """Allow only presentation, accessibility, and safe link attributes."""
    if name in {"id", "class", "tabindex", "title", "rel"}:
        return True
    if name.startswith("data-") or name.startswith("aria-"):
        return True
    if tag == "a" and name == "href":
        return True
    return False


def _sanitize_html(html: str) -> str:
    """Remove active/untrusted markup from source documents before publishing."""
    without_active_content = re.sub(
        r"<(?:script|iframe|object|embed)\b[^>]*>.*?</(?:script|iframe|object|embed)\s*>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    without_active_content = re.sub(
        r"<(?:script|iframe|object|embed)\b[^>]*?/?>",
        "",
        without_active_content,
        flags=re.IGNORECASE,
    )
    cleaned = bleach.clean(
        without_active_content,
        tags=_ALLOWED_TAGS,
        attributes=_allowed_attribute,
        protocols=frozenset({"http", "https", "mailto"}),
        strip=True,
    )
    return cleaned
