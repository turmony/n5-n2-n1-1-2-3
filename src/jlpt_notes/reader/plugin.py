"""MkDocs integration for the read-only JLPT LAN reader."""

from hashlib import sha256
from html import escape
import json
from pathlib import Path
import re
from typing import Any

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
        self._url_hashes: dict[str, str] = {}
        return config

    def on_files(self, files: Files, config, **kwargs: Any) -> Files:
        pages = (*self._pages, build_catalog_page(self._pages))
        virtual: list[File] = []
        for source in pages:
            file = File(
                source.output_path.as_posix(),
                str(self._source_root),
                config.site_dir,
                config.use_directory_urls,
            )
            file.content_string = source.markdown
            self._pages_by_uri[file.src_uri] = source
            virtual.append(file)
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
    """Reserve the H1 for the generated display title."""
    return re.sub(
        r"^(#{1,5})(?=\s)",
        lambda match: "#" + match.group(1),
        markdown,
        flags=re.MULTILINE,
    )


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
