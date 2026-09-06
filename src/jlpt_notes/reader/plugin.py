"""MkDocs integration for the read-only JLPT LAN reader."""

from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import posixpath
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import bleach
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor
from mkdocs import plugins, utils
from mkdocs.config import base, config_options as c
from mkdocs.structure.files import File, Files
from pymdownx.slugs import slugify

from .metadata import render_metadata_block
from .sources import SourcePage, build_catalog_page, load_source_pages
from .submissions import find_answer_block, is_blank_answer_area, parse_paper_structure


class ReaderPluginConfig(base.Config):
    """Configuration for the reader's packaged presentation assets."""

    assets_dir = c.Type(str, default="assets")


class _ReaderVirtualFile(File):
    """Let MkDocs dirty builds skip copied HTML for byte-identical sources."""

    def __init__(self, *args: Any, reader_modified: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reader_modified = reader_modified

    def is_modified(self) -> bool:
        return self.reader_modified


class JlptReaderPlugin(plugins.BasePlugin[ReaderPluginConfig]):
    """Expose a read-only source tree as generated MkDocs pages."""

    def configure_incremental(self, previous_site: Path) -> None:
        """Reuse one immutable published generation as a build input copy."""
        self._incremental_site = previous_site.resolve(strict=True)

    def on_config(self, config, **kwargs: Any):
        config["mdx_configs"].setdefault("toc", {}).setdefault("slugify", slugify())
        config["markdown_extensions"].append(ReaderHeadingExtension())
        self._source_root = Path(config.docs_dir).resolve(strict=True)
        self._config_path = Path(config.config_file_path).resolve(strict=True)
        self._config_root = self._config_path.parent
        self._pages = load_source_pages(self._source_root)
        self._pages_by_uri: dict[str, SourcePage] = {}
        self._files_by_relative_path: dict[Path, File] = {}
        self._pager_neighbours: dict[str, tuple[tuple[str, str] | None, tuple[str, str] | None]] = {}
        self._url_hashes: dict[str, str] = {}
        self._previous_manifest: dict[str, Any] | None = None
        self._previous_search: dict[str, Any] | None = None
        self._incremental_enabled = False
        self._modified_urls: set[str] = set()
        self._reused_files: list[File] = []
        self.rendered_pages = 0
        self.reused_pages = 0
        previous_site = getattr(self, "_incremental_site", None)
        if previous_site is not None:
            try:
                manifest = json.loads(
                    (previous_site / "reader-version.json").read_text(encoding="utf-8")
                )
                search = json.loads(
                    (previous_site / "search/search_index.json").read_text(encoding="utf-8")
                )
                if (
                    not isinstance(manifest.get("version"), str)
                    or not manifest["version"]
                    or not isinstance(manifest.get("pages"), dict)
                    or not isinstance(search.get("docs"), list)
                ):
                    raise ValueError("incomplete incremental reader metadata")
                self._previous_manifest = manifest
                self._previous_search = search
            except (OSError, ValueError, json.JSONDecodeError):
                self._previous_manifest = None
                self._previous_search = None
        return config

    def on_files(self, files: Files, config, **kwargs: Any) -> Files:
        retained = [file for file in files if not _originates_below(file, self._source_root)]
        virtual: list[File] = []
        source_files: list[tuple[SourcePage, _ReaderVirtualFile]] = []
        for source in self._pages:
            file = _ReaderVirtualFile(
                _virtual_source_path(source).as_posix(),
                str(self._source_root),
                config.site_dir,
                config.use_directory_urls,
            )
            file.content_string = source.markdown
            self._pages_by_uri[file.src_uri] = source
            self._files_by_relative_path[source.relative_path] = file
            virtual.append(file)
            source_files.append((source, file))
        catalog = build_catalog_page(self._pages)
        catalog = SourcePage(
            relative_path=catalog.relative_path,
            output_path=catalog.output_path,
            markdown=_catalog_with_final_urls(catalog.markdown, self._files_by_relative_path),
            metadata=catalog.metadata,
            content_hash=catalog.content_hash,
            warning=catalog.warning,
        )
        catalog_file = _ReaderVirtualFile(
            "index.md",
            str(self._source_root),
            config.site_dir,
            config.use_directory_urls,
        )
        catalog_file.content_string = catalog.markdown
        self._pages_by_uri[catalog_file.src_uri] = catalog
        virtual.insert(0, catalog_file)
        source_files.insert(0, (catalog, catalog_file))
        self._pager_neighbours = _grammar_pager_neighbours(source_files)

        navigation_fingerprint = _navigation_fingerprint(source_files)
        presentation_fingerprint = _presentation_fingerprint(
            self._config_path,
            self._config_root,
            self.config.assets_dir,
        )
        previous = self._previous_manifest or {}
        previous_hashes = previous.get("pages", {})
        self._incremental_enabled = bool(
            self._previous_search is not None
            and previous.get("navigation") == navigation_fingerprint
            and previous.get("presentation") == presentation_fingerprint
        )
        if getattr(self, "_incremental_site", None) is not None and not self._incremental_enabled:
            utils.clean_directory(config.site_dir)
        for source, file in source_files:
            file.reader_modified = not self._incremental_enabled or (
                previous_hashes.get(file.url) != source.content_hash
            )
            if file.reader_modified:
                self._modified_urls.add(file.url)
                self.rendered_pages += 1
            else:
                self._reused_files.append(file)
                self.reused_pages += 1
        self._navigation_hash = navigation_fingerprint
        self._presentation_hash = presentation_fingerprint
        for name in ("reader.css", "reader.js", "quiz-answer.js"):
            source_path = self._config_root / self.config.assets_dir / name
            file = File(
                f"assets/{name}",
                str(self._source_root),
                config.site_dir,
                config.use_directory_urls,
            )
            file.content_bytes = source_path.read_bytes()
            virtual.append(file)
        self._url_hashes = {
            file.url: self._pages_by_uri[file.src_uri].content_hash
            for file in virtual
            if file.src_uri in self._pages_by_uri
        }
        self._generation_version = _generation_version(self._url_hashes)
        return Files([*retained, *virtual])

    def on_nav(self, nav, config, files, **kwargs: Any):
        for page in nav.pages:
            source = self._pages_by_uri.get(page.file.src_uri)
            if source is not None:
                page.title = source.metadata.display_title
        _hoist_synthetic_library(nav.items)
        _localize_and_sort_navigation(nav.items, self._pages_by_uri)
        return nav

    def on_page_markdown(self, markdown: str, page, **kwargs: Any) -> str:
        source = self._pages_by_uri[page.file.src_uri]
        page.title = source.metadata.display_title
        page.meta.update(
            {
                "reader_level": source.metadata.level or "",
                "reader_type": source.metadata.content_type,
                "reader_page_key": page.file.url,
                "reader_page_hash": source.content_hash,
                "reader_generation": self._generation_version,
            }
        )
        warning = f'!!! warning "读取提示"\n    {source.warning}\n\n' if source.warning else ""
        safe_title = escape(source.metadata.display_title)
        page_state = (
            '<div class="jlpt-page-state" aria-hidden="true" '
            f'data-page-key="{escape(page.file.url, quote=True)}" '
            f'data-page-hash="{source.content_hash}" '
            f'data-generation="{self._generation_version}" '
            f'data-reader-type="{escape(source.metadata.content_type, quote=True)}"></div>'
        )
        neighbours = self._pager_neighbours.get(page.file.src_uri)
        pager = ""
        if neighbours is not None:
            previous, nxt = neighbours
            pager = _render_card_pager(
                None if previous is None else (_pager_href(previous[0], page.file.url), previous[1]),
                None if nxt is None else (_pager_href(nxt[0], page.file.url), nxt[1]),
            )
        quiz_state = _quiz_state_div(source)
        return (
            f"# {safe_title}\n\n{page_state}\n\n{quiz_state}"
            f"{render_metadata_block(source.metadata)}\n\n{warning}{markdown}"
            + (f"\n\n{pager}" if pager else "")
        )

    def on_page_content(self, html: str, page, **kwargs: Any) -> str:
        """Keep generated page HTML readable while removing unsafe source HTML."""
        cleaned = _sanitize_html(_demote_raw_html_h1_after_title(html))
        source = self._pages_by_uri.get(page.file.src_uri)
        if source is not None and source.metadata.content_type == "catalog":
            cleaned = cleaned.replace(
                '<ul class="jlpt-catalog"',
                f"{_FULLTEXT_SEARCH_CONTROL}\n<ul class=\"jlpt-catalog\"",
                1,
            )
        return cleaned

    def on_page_context(self, context, page, config, nav, **kwargs: Any):
        source = self._pages_by_uri.get(page.file.src_uri)
        if source is not None:
            self._url_hashes[page.file.url] = source.content_hash
        return context

    @plugins.event_priority(-100)
    def on_post_build(self, config, **kwargs: Any) -> None:
        if self._incremental_enabled:
            self._merge_incremental_search(Path(config.site_dir))
            previous_generation = str((self._previous_manifest or {})["version"])
            for file in self._reused_files:
                _refresh_reused_generation(
                    Path(file.abs_dest_path),
                    self._generation_version,
                    previous_generation,
                )
        manifest = {
            "version": self._generation_version,
            "navigation": self._navigation_hash,
            "presentation": self._presentation_hash,
            "pages": dict(sorted(self._url_hashes.items())),
        }
        (Path(config.site_dir) / "reader-version.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _merge_incremental_search(self, site_dir: Path) -> None:
        search_path = site_dir / "search/search_index.json"
        current = json.loads(search_path.read_text(encoding="utf-8"))
        previous_docs = list((self._previous_search or {}).get("docs", ()))
        retained = [
            document
            for document in previous_docs
            if not any(
                _search_location_belongs_to(str(document.get("location", "")), url)
                for url in self._modified_urls
            )
        ]
        current["docs"] = retained + list(current.get("docs", ()))
        search_path.write_text(
            json.dumps(current, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def _originates_below(file: File, root: Path) -> bool:
    """Return whether an incoming MkDocs file exposes the reader's source tree."""
    if file.src_dir is None:
        return False
    return Path(file.src_dir).resolve(strict=False) == root


def _generation_version(url_hashes: dict[str, str]) -> str:
    ordered = sorted(url_hashes.items())
    version_source = "".join(f"{url}\0{content_hash}\n" for url, content_hash in ordered)
    return sha256(version_source.encode("utf-8")).hexdigest()


def _quiz_state_div(source: SourcePage) -> str:
    """Embed machine-readable quiz state for paper pages only."""
    parts = source.relative_path.parts
    if (
        len(parts) != 3
        or parts[0] != "quizzes"
        or parts[1] != "papers"
        or source.relative_path.suffix.lower() != ".md"
    ):
        return ""
    questions, part_groups = parse_paper_structure(source.markdown)
    if not questions:
        return ""
    block = find_answer_block(source.markdown)
    state = {
        "paper": source.relative_path.name,
        "answered": block is not None and not is_blank_answer_area(block[2]),
        "questions": [
            {"number": q.number, "kind": q.kind, "options": q.option_count} for q in questions
        ],
        "parts": [
            {"ordinal": ordinal, "numbers": list(numbers)} for ordinal, _title, numbers in part_groups
        ],
    }
    payload = escape(json.dumps(state, ensure_ascii=False), quote=True)
    return f'<div class="jlpt-quiz-state" data-quiz-state="{payload}" hidden></div>\n\n'


class ReaderHeadingExtension(Extension):
    """Demote parsed source headings before MkDocs' TOC processor assigns anchors."""

    def extendMarkdown(self, md) -> None:
        md.treeprocessors.register(_DemoteSourceHeadingTreeprocessor(md), "jlpt_reader_headings", 6)


class _DemoteSourceHeadingTreeprocessor(Treeprocessor):
    def run(self, root: ElementTree.Element) -> ElementTree.Element:
        generated_title_seen = False
        for element in root.iter():
            if element.tag == "h1":
                if generated_title_seen:
                    element.tag = "h2"
                else:
                    generated_title_seen = True
            elif element.tag in {"h2", "h3", "h4", "h5"}:
                element.tag = f"h{int(element.tag[1]) + 1}"
        return root


class _RawH1Demoter(HTMLParser):
    """Demote raw source H1 tags without interpreting escaped code text as markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self._h1_count = 0
        self._h1_end_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        raw = self.get_starttag_text() or f"<{tag}>"
        if tag.casefold() == "h1":
            self._h1_count += 1
            replacement = "h1" if self._h1_count == 1 else "h2"
            self._h1_end_tags.append(replacement)
            self.parts.append(re.sub(r"^(<\s*)h1\b", rf"\1{replacement}", raw, flags=re.IGNORECASE))
            return
        self.parts.append(raw)

    def handle_startendtag(self, tag: str, attrs) -> None:
        raw = self.get_starttag_text() or f"<{tag} />"
        if tag.casefold() == "h1":
            self._h1_count += 1
            replacement = "h1" if self._h1_count == 1 else "h2"
            self.parts.append(re.sub(r"^(<\s*)h1\b", rf"\1{replacement}", raw, flags=re.IGNORECASE))
            return
        self.parts.append(raw)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "h1" and self._h1_end_tags:
            self.parts.append(f"</{self._h1_end_tags.pop()}>")
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")


def _demote_raw_html_h1_after_title(html: str) -> str:
    parser = _RawH1Demoter()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


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


def _hoist_synthetic_library(items) -> None:
    """Hide the virtual storage namespace while retaining the source-folder tree."""
    for index, item in enumerate(items):
        if str(getattr(item, "title", "")).casefold() != "library":
            continue
        children = list(getattr(item, "children", ()))
        for child in children:
            child.parent = None
        items[index : index + 1] = children
        return


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
    top_folder = source.relative_path.parts[0].casefold() if source.relative_path.parts else ""
    is_dated = top_folder in {"quizzes", "reviews", "history"}
    date = re.search(r"\d{4}-\d{2}-\d{2}", relative)
    if is_dated and date:
        return (1, -int(date.group(0).replace("-", "")), relative.casefold(), relative)
    return (2, relative.casefold(), relative)


def _render_card_pager(
    previous: tuple[str, str] | None,
    nxt: tuple[str, str] | None,
) -> str:
    """Render the same-level grammar pager; empty when no neighbour exists."""

    def link(side: str, label: str, target: tuple[str, str]) -> str:
        url, title = target
        return (
            f'<a class="jlpt-card-pager__link jlpt-card-pager__link--{side}" '
            f'href="{escape(url, quote=True)}">'
            f'<span class="jlpt-card-pager__label">{label}</span>'
            f'<span class="jlpt-card-pager__title">{escape(title)}</span></a>'
        )

    links: list[str] = []
    if previous is not None:
        links.append(link("prev", "← 上一张卡", previous))
    if nxt is not None:
        links.append(link("next", "下一张卡 →", nxt))
    if not links:
        return ""
    return '<nav class="jlpt-card-pager" aria-label="语法卡翻阅">' + "".join(links) + "</nav>"


def _pager_href(target_url: str, page_url: str) -> str:
    """Turn a site-root-relative URL into a href relative to the current page."""
    base = page_url if page_url.endswith("/") else posixpath.dirname(page_url)
    relative = posixpath.relpath(target_url, base or ".").replace("\\", "/")
    if target_url.endswith("/") and not relative.endswith("/"):
        # Directory URLs keep their trailing slash so served pages resolve without redirects.
        relative += "/"
    return relative


def _grammar_pager_neighbours(
    source_files: list[tuple[SourcePage, File]],
) -> dict[str, tuple[tuple[str, str] | None, tuple[str, str] | None]]:
    """Map each grammar page to its same-level previous/next card targets."""
    groups: dict[str, list[tuple[SourcePage, File]]] = {}
    for source, file in source_files:
        level = source.metadata.level
        if source.metadata.content_type != "grammar" or not level:
            continue
        groups.setdefault(level, []).append((source, file))
    neighbours: dict[str, tuple[tuple[str, str] | None, tuple[str, str] | None]] = {}
    for entries in groups.values():
        entries.sort(key=lambda entry: _source_navigation_key(entry[0]))
        for index, (source, file) in enumerate(entries):
            previous = entries[index - 1] if index > 0 else None
            nxt = entries[index + 1] if index + 1 < len(entries) else None
            if previous is None and nxt is None:
                continue
            neighbours[file.src_uri] = (
                None if previous is None else (previous[1].url, previous[0].metadata.display_title),
                None if nxt is None else (nxt[1].url, nxt[0].metadata.display_title),
            )
    return neighbours


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
        "nav",
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


_FULLTEXT_SEARCH_CONTROL = """<form class="jlpt-fulltext-search" data-jlpt-fulltext="" role="search">
<label for="jlpt-fulltext-query">全文搜索</label>
<input id="jlpt-fulltext-query" type="search" inputmode="search" autocomplete="off" spellcheck="false" placeholder="连续输入日文、中文、编号或标签" aria-describedby="jlpt-fulltext-status" disabled>
<p id="jlpt-fulltext-status" class="jlpt-fulltext-status" role="status" aria-live="polite">正在载入本地全文索引……</p>
</form>"""


def _allowed_attribute(tag: str, name: str, value: str) -> bool:
    """Allow only presentation, accessibility, and safe link attributes."""
    if name in {"id", "class", "tabindex", "title", "rel", "hidden"}:
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


def _navigation_fingerprint(
    source_files: list[tuple[SourcePage, _ReaderVirtualFile]],
) -> str:
    values = [
        (
            source.relative_path.as_posix(),
            file.url,
            source.metadata.display_title,
            source.metadata.source_id or "",
            source.metadata.content_type,
            source.metadata.level or "",
        )
        for source, file in source_files
    ]
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _presentation_fingerprint(
    config_path: Path,
    config_root: Path,
    assets_dir: str,
) -> str:
    digest = sha256(b"jlpt-reader-rendering-v2\0")
    candidates = [config_path]
    for directory in (config_root / assets_dir, config_root / "overrides"):
        if directory.is_dir():
            candidates.extend(path for path in directory.rglob("*") if path.is_file())
    for path in sorted(candidates, key=lambda item: (item.as_posix().casefold(), item.as_posix())):
        if not path.is_file():
            continue
        digest.update(path.relative_to(config_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _search_location_belongs_to(location: str, page_url: str) -> bool:
    base = page_url.rstrip("/")
    candidate = location.rstrip("/")
    return candidate == base or location.startswith(f"{page_url}#")


def _refresh_reused_generation(path: Path, generation: str, previous_generation: str) -> None:
    html = path.read_bytes()
    previous = previous_generation.encode("utf-8")
    replacement = generation.encode("utf-8")
    old_meta = b'<meta name="jlpt-generation" content="' + previous + b'">'
    new_meta = b'<meta name="jlpt-generation" content="' + replacement + b'">'
    state_start = html.find(b'<div class="jlpt-page-state"')
    state_end = html.find(b">", state_start) if state_start >= 0 else -1
    old_state = b'data-generation="' + previous + b'"'
    new_state = b'data-generation="' + replacement + b'"'
    state = html[state_start:state_end] if state_end >= 0 else b""
    if html.count(old_meta) != 1 or state.count(old_state) != 1:
        raise ValueError(f"Cached reader page has no generation markers: {path}")
    refreshed = html.replace(old_meta, new_meta, 1)
    state_start = refreshed.find(b'<div class="jlpt-page-state"')
    state_end = refreshed.find(b">", state_start)
    state = refreshed[state_start:state_end].replace(old_state, new_state, 1)
    path.write_bytes(refreshed[:state_start] + state + refreshed[state_end:])
