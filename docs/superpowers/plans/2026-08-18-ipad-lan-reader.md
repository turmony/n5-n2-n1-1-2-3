# JLPT iPad LAN Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a manually started, strictly read-only Material for MkDocs website that renders the existing `jlpt-notes` repository for comfortable iPad reading over a private Windows LAN.

**Architecture:** Material for MkDocs supplies responsive navigation, typography, themes, and browser-side search. A project-local MkDocs plugin adapts the repository's JSON frontmatter, titles, drafts, quizzes, and JSONL files without modifying source data; a Tkinter launcher builds versioned temporary sites, serves only generated files over GET/HEAD, watches for changes, and shows the private-LAN URL.

**Tech Stack:** Python 3.10+, `unittest`, MkDocs 1.6+, Material for MkDocs 9.6+, Bleach 6.x, Python standard-library Tkinter/HTTP/threading/tempfile, Windows PowerShell and Firewall cmdlets.

**Spec:** `docs/superpowers/specs/2026-08-18-ipad-lan-reader-design.md`

## Global Constraints

- Treat `jlpt-notes` as the single source of truth and open it read-only.
- Never create cache, generated HTML, logs, firewall state, or helper files inside `jlpt-notes`.
- Discover only `jlpt-notes/**/*.md` and `jlpt-notes/**/*.jsonl`; do not expose any other project file.
- Do not move the repository or require OneDrive, SMB, a Windows password, an iPad app, or internet access.
- Serve only generated site files and accept only HTTP `GET` and `HEAD`.
- Bind for LAN access only when an active Windows network is categorized `Private` and the firewall rule is scoped to `Private` plus `LocalSubnet`.
- Use fixed port `8765`; fail visibly instead of silently selecting another port.
- Start only through an explicit user action; do not create a login item, scheduled task, or Windows service.
- Do not register a Service Worker or cache rendered learning content for offline use.
- Preserve the existing confirmation-before-entry and seven-day-review behavior; the reader must not call repository write APIs.
- Follow the repository's existing `unittest` style and run the full suite after every task.
- Preserve all pre-existing working-tree changes and stage only files named by the current task.

---

## Planned File Structure

```text
pyproject.toml
src/jlpt_notes/cli.py
src/jlpt_notes/reader/
├─ __init__.py
├─ metadata.py             # Generic JSON-frontmatter parsing and display titles
├─ sources.py              # Read-only discovery, JSONL conversion, catalog generation
├─ plugin.py               # MkDocs plugin and generated manifest
├─ builder.py              # Temporary MkDocs builds and active-site switching
├─ watcher.py              # Debounced source snapshots
├─ server.py               # GET/HEAD-only static HTTP server
├─ network.py              # Private-network address discovery
├─ firewall.py             # Firewall status and explicit setup launch
├─ controller.py           # Reader lifecycle orchestration
└─ launcher.py             # Tkinter control window
reader/
├─ mkdocs.yml
├─ overrides/main.html
├─ assets/reader.css
├─ assets/reader.js
├─ configure-firewall.ps1
└─ install-shortcut.ps1
tests/reader/
├─ __init__.py
├─ test_metadata.py
├─ test_sources.py
├─ test_plugin.py
├─ test_builder.py
├─ test_watcher.py
├─ test_server.py
├─ test_network.py
├─ test_firewall.py
├─ test_controller.py
└─ test_end_to_end.py
```

The package modules stay small and communicate through the exact interfaces listed per task. Theme files live outside `jlpt-notes`; the plugin injects them into the generated site as virtual files.

---

### Task 1: Dependencies and Generic Markdown Metadata

**Files:**
- Modify: `pyproject.toml`
- Create: `src/jlpt_notes/reader/__init__.py`
- Create: `src/jlpt_notes/reader/metadata.py`
- Create: `tests/reader/__init__.py`
- Create: `tests/reader/test_metadata.py`

**Interfaces:**
- Produces: `DocumentMetadata`, `ParsedMarkdown`, and `parse_markdown(relative_path: Path, text: str) -> ParsedMarkdown`.
- Produces: `render_metadata_block(metadata: DocumentMetadata) -> str` for Task 3.
- Consumes: only Python standard-library `json`, `re`, `dataclasses`, `html`, and `pathlib`.

- [ ] **Step 1: Add failing tests for formal cards, drafts, reports, and malformed metadata**

```python
# tests/reader/test_metadata.py
import unittest
from pathlib import Path

from jlpt_notes.reader.metadata import parse_markdown, render_metadata_block


class ReaderMetadataTests(unittest.TestCase):
    def test_formal_card_uses_full_id_and_title(self) -> None:
        text = '''---
{"id":"N5-G-0001","level":"N5","kind":"grammar","title":"～です","status":"confirmed","tags":["丁寧体"],"next_review":"2026-08-25"}
---

# 核心用法
正文
'''
        parsed = parse_markdown(Path("grammar/n5/N5-G-0001.md"), text)
        self.assertEqual(parsed.metadata.display_title, "N5-G-0001｜～です")
        self.assertEqual(parsed.metadata.level, "N5")
        self.assertEqual(parsed.metadata.content_type, "grammar")
        self.assertEqual(parsed.metadata.tags, ("丁寧体",))
        self.assertEqual(parsed.body, "# 核心用法\n正文\n")

    def test_draft_reads_nested_proposal(self) -> None:
        text = '''---
{"draft_id":"draft-20260805-n4-g-0055","confirmed":true,"proposal":{"id":"N4-G-0055","level":"N4","kind":"grammar","title":"～ように言います","status":"confirmed"}}
---

## 学习者原始输出
正文
'''
        parsed = parse_markdown(Path("drafts/draft-20260805-n4-g-0055.md"), text)
        self.assertEqual(parsed.metadata.display_title, "N4-G-0055｜草稿｜～ように言います")
        self.assertEqual(parsed.metadata.content_type, "draft")

    def test_report_uses_level_date_and_heading_without_inventing_id(self) -> None:
        text = "# 2026-07-27 N5 全语法综合诊断卷（二）：作答报告\n\n正文\n"
        parsed = parse_markdown(
            Path("quizzes/results/2026-07-27-n5-comprehensive-test-2-result.md"), text
        )
        self.assertEqual(parsed.metadata.display_title, "N5｜2026-07-27｜全语法综合诊断卷（二）：作答报告")
        self.assertIsNone(parsed.metadata.source_id)

    def test_malformed_frontmatter_keeps_body_and_returns_warning(self) -> None:
        parsed = parse_markdown(Path("drafts/broken.md"), "---\n{bad json}\n---\n\n# 可读正文\n")
        self.assertIn("元数据无法解析", parsed.warning or "")
        self.assertIn("# 可读正文", parsed.body)

    def test_metadata_block_escapes_values(self) -> None:
        parsed = parse_markdown(
            Path("grammar/n5/x.md"),
            '---\n{"id":"N5-G-9999","level":"N5","kind":"grammar","title":"<script>x</script>","tags":[]}\n---\n\n正文\n',
        )
        block = render_metadata_block(parsed.metadata)
        self.assertNotIn("<script>", block)
        self.assertIn("&lt;script&gt;", block)
```

- [ ] **Step 2: Run the new tests and confirm the missing module failure**

Run:

```powershell
python -m unittest tests.reader.test_metadata -v
```

Expected: `ModuleNotFoundError: No module named 'jlpt_notes.reader'`.

- [ ] **Step 3: Add bounded dependencies and implement the metadata types and parser**

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
  "mkdocs>=1.6,<2",
  "mkdocs-material>=9.6,<10",
  "bleach>=6,<7",
]
```

Implement these exact public types in `metadata.py`:

```python
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
    return ParsedMarkdown(DocumentMetadata(display_title, level, content_type, source_id, tags, fields), body, warning)


def render_metadata_block(metadata: DocumentMetadata) -> str:
    chips = "".join(
        f'<span class="jlpt-meta-chip"><b>{escape(label)}</b> {escape(value)}</span>'
        for label, value in metadata.fields
    )
    return f'<div class="jlpt-meta" aria-label="资料信息">{chips}</div>' if chips else ""
```

Implement private helpers with these rules: `_first_text` skips empty values; `_level_from_path` recognizes `N1`–`N5` case-insensitively; `_first_heading` removes a leading date from reports; `_content_type` maps `grammar`, `drafts`, `quizzes/questions`, `quizzes/results`, `reviews`, and `history`; `_display_title` uses the formats in the spec and never invents an ID; `_display_fields` emits only present values in the order 等级、类型、状态、标签、创建、更新、下次复习、来源.

- [ ] **Step 4: Install the editable package and run focused plus full tests**

Run:

```powershell
python -m pip install -e .
python -m unittest tests.reader.test_metadata -v
python -m unittest discover -s tests -v
```

Expected: all tests pass; existing repository behavior is unchanged.

- [ ] **Step 5: Commit Task 1**

```powershell
git add pyproject.toml src/jlpt_notes/reader/__init__.py src/jlpt_notes/reader/metadata.py tests/reader/__init__.py tests/reader/test_metadata.py
git commit -m "feat: parse JLPT reader metadata"
```

---

### Task 2: Read-Only Source Discovery, JSONL Pages, and Catalog

**Files:**
- Create: `src/jlpt_notes/reader/sources.py`
- Create: `tests/reader/test_sources.py`

**Interfaces:**
- Consumes: `parse_markdown()` from Task 1.
- Produces: `SourcePage(relative_path, output_path, markdown, metadata, content_hash, warning)`.
- Produces: `load_source_pages(root: Path) -> tuple[SourcePage, ...]`.
- Produces: `build_catalog_page(pages: tuple[SourcePage, ...]) -> SourcePage`.

- [ ] **Step 1: Write failing discovery and JSONL tests**

```python
# tests/reader/test_sources.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.reader.sources import build_catalog_page, load_source_pages


class ReaderSourceTests(unittest.TestCase):
    def test_discovers_only_markdown_and_jsonl_without_following_symlinks(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "grammar").mkdir()
            (root / "grammar/card.md").write_text("# N5 卡片\n", encoding="utf-8")
            (root / "events.jsonl").write_text('{"id":"e1","result":"wrong"}\n', encoding="utf-8")
            (root / "secret.txt").write_text("secret", encoding="utf-8")
            (root / ".hidden.md").write_text("hidden", encoding="utf-8")
            pages = load_source_pages(root)
            self.assertEqual([p.relative_path.as_posix() for p in pages], ["events.jsonl", "grammar/card.md"])
            self.assertEqual(pages[0].output_path.as_posix(), "events.jsonl.md")

    def test_jsonl_bad_line_is_isolated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "events.jsonl").write_text('{"id":"e1"}\nnot-json\n{"id":"e3"}\n', encoding="utf-8")
            page = load_source_pages(root)[0]
            self.assertIn("记录 1", page.markdown)
            self.assertIn("第 2 行无法解析", page.markdown)
            self.assertIn("记录 3", page.markdown)

    def test_catalog_contains_filter_data_and_titles(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "grammar/n5/N5-G-0001.md"
            path.parent.mkdir(parents=True)
            path.write_text('---\n{"id":"N5-G-0001","level":"N5","kind":"grammar","title":"～です"}\n---\n\n正文\n', encoding="utf-8")
            catalog = build_catalog_page(load_source_pages(root))
            self.assertEqual(catalog.output_path.as_posix(), "index.md")
            self.assertIn('data-level="N5"', catalog.markdown)
            self.assertIn("N5-G-0001｜～です", catalog.markdown)
```

- [ ] **Step 2: Verify the tests fail because `sources.py` does not exist**

```powershell
python -m unittest tests.reader.test_sources -v
```

Expected: import failure for `jlpt_notes.reader.sources`.

- [ ] **Step 3: Implement immutable source pages and deterministic discovery**

```python
# src/jlpt_notes/reader/sources.py
from dataclasses import dataclass
from hashlib import sha256
from html import escape
import json
from pathlib import Path

from .metadata import DocumentMetadata, ParsedMarkdown, parse_markdown


@dataclass(frozen=True)
class SourcePage:
    relative_path: Path
    output_path: Path
    markdown: str
    metadata: DocumentMetadata
    content_hash: str
    warning: str | None = None


def load_source_pages(root: Path) -> tuple[SourcePage, ...]:
    resolved_root = root.resolve(strict=True)
    pages: list[SourcePage] = []
    for path in sorted(resolved_root.rglob("*"), key=lambda item: item.relative_to(resolved_root).as_posix().casefold()):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".md", ".jsonl"}:
            continue
        relative = path.relative_to(resolved_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        resolved = path.resolve(strict=True)
        if resolved_root not in resolved.parents:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".jsonl":
            parsed = _parse_jsonl(relative, text)
            output_path = relative.with_suffix(relative.suffix + ".md")
        else:
            parsed = parse_markdown(relative, text)
            output_path = relative
        pages.append(SourcePage(relative, output_path, parsed.body, parsed.metadata, sha256(text.encode("utf-8")).hexdigest(), parsed.warning))
    return tuple(pages)
```

Implement `_parse_jsonl()` to use `json.loads` per nonblank line, render escaped JSON in `<details>` blocks, and add a visible warning for a bad line. Implement `build_catalog_page()` as a generated `index.md` `SourcePage` with `warning=None`; its entries contain `data-level`, `data-type`, and `data-tags` attributes and relative links to each output page. Sort structured IDs numerically, dated files newest first within report-like sections, then use case-folded paths.

- [ ] **Step 4: Run source tests and the full suite**

```powershell
python -m unittest tests.reader.test_sources -v
python -m unittest discover -s tests -v
```

Expected: all tests pass; discovery never returns `secret.txt`.

- [ ] **Step 5: Commit Task 2**

```powershell
git add src/jlpt_notes/reader/sources.py tests/reader/test_sources.py
git commit -m "feat: discover read-only learning sources"
```

---

### Task 3: MkDocs Plugin and Virtual Pages

**Files:**
- Modify: `pyproject.toml`
- Create: `src/jlpt_notes/reader/plugin.py`
- Create: `tests/reader/test_plugin.py`

**Interfaces:**
- Consumes: `load_source_pages()`, `build_catalog_page()`, and `render_metadata_block()`.
- Produces: MkDocs plugin entry point `jlpt_reader`.
- Produces generated `reader-version.json` with `version` and URL-keyed `pages` hashes.
- Produces virtual `index.md`, transformed Markdown pages, JSONL pages, `assets/reader.css`, and `assets/reader.js`.

- [ ] **Step 1: Write a failing plugin build test**

```python
# tests/reader/test_plugin.py
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mkdocs.commands.build import build
from mkdocs.config import load_config


class ReaderPluginTests(unittest.TestCase):
    def test_build_uses_display_title_and_does_not_copy_raw_sources(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            docs = base / "jlpt-notes"
            docs.mkdir()
            (docs / "card.md").write_text(
                '---\n{"id":"N5-G-0001","level":"N5","kind":"grammar","title":"～です"}\n---\n\n# 核心\n正文\n',
                encoding="utf-8",
            )
            (docs / "events.jsonl").write_text('{"id":"e1"}\n', encoding="utf-8")
            assets = base / "assets"
            assets.mkdir()
            (assets / "reader.css").write_text(".jlpt-meta{}", encoding="utf-8")
            (assets / "reader.js").write_text("", encoding="utf-8")
            config_file = base / "mkdocs.yml"
            config_file.write_text(
                "site_name: JLPT\ntheme:\n  name: material\nplugins:\n  - jlpt_reader:\n      assets_dir: assets\n  - search\n",
                encoding="utf-8",
            )
            site = base / "site"
            config = load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site))
            build(config)
            html = (site / "card/index.html").read_text(encoding="utf-8")
            self.assertIn("N5-G-0001｜～です", html)
            self.assertIn("jlpt-meta", html)
            self.assertIn('<h2 id="核心">核心</h2>', html)
            self.assertFalse((site / "events.jsonl").exists())
            self.assertTrue((site / "events.jsonl/index.html").exists())
            manifest = json.loads((site / "reader-version.json").read_text(encoding="utf-8"))
            self.assertIn("card/", manifest["pages"])
```

- [ ] **Step 2: Run the test and confirm the missing plugin entry point**

```powershell
python -m unittest tests.reader.test_plugin -v
```

Expected: MkDocs reports that the `jlpt_reader` plugin is not installed.

- [ ] **Step 3: Register and implement the plugin**

Add the entry point:

```toml
[project.entry-points."mkdocs.plugins"]
jlpt_reader = "jlpt_notes.reader.plugin:JlptReaderPlugin"
```

Implement the plugin with these hooks:

```python
from hashlib import sha256
from html import escape
import json
from pathlib import Path

import bleach
from mkdocs import plugins
from mkdocs.config import base, config_options as c
from mkdocs.structure.files import File, Files

from .metadata import render_metadata_block
from .sources import SourcePage, build_catalog_page, load_source_pages


class ReaderPluginConfig(base.Config):
    assets_dir = c.Type(str, default="assets")


class JlptReaderPlugin(plugins.BasePlugin[ReaderPluginConfig]):
    def on_config(self, config, **kwargs):
        self._source_root = Path(config.docs_dir).resolve(strict=True)
        self._config_root = Path(config.config_file_path).resolve().parent
        self._pages = load_source_pages(self._source_root)
        self._pages_by_uri: dict[str, SourcePage] = {}
        self._url_hashes: dict[str, str] = {}
        return config

    def on_files(self, files, config, **kwargs):
        pages = (*self._pages, build_catalog_page(self._pages))
        virtual: list[File] = []
        for source in pages:
            file = File(source.output_path.as_posix(), str(self._source_root), config.site_dir, config.use_directory_urls)
            file.content_string = source.markdown
            self._pages_by_uri[file.src_uri] = source
            virtual.append(file)
        for name in ("reader.css", "reader.js"):
            source_path = self._config_root / self.config.assets_dir / name
            file = File(f"assets/{name}", str(self._source_root), config.site_dir, config.use_directory_urls)
            file.content_bytes = source_path.read_bytes()
            virtual.append(file)
        return Files(virtual)

    def on_page_markdown(self, markdown, page, **kwargs):
        source = self._pages_by_uri[page.file.src_uri]
        page.title = source.metadata.display_title
        page.meta.update({"reader_level": source.metadata.level or "", "reader_type": source.metadata.content_type})
        warning = f'!!! warning "读取提示"\n    {source.warning}\n\n' if source.warning else ""
        body = _demote_headings(markdown)
        safe_title = escape(source.metadata.display_title)
        return f"# {safe_title}\n\n{render_metadata_block(source.metadata)}\n\n{warning}{body}"
```

Implement `_demote_headings()` with `re.sub(r"^(#{1,5})(?=\s)", lambda match: "#" + match.group(1), markdown, flags=re.MULTILINE)` so the generated display title is the sole H1. Complete `on_nav` so each internal `Page.title` is set from `_pages_by_uri`. Complete `on_page_content` using `bleach.clean()` with an explicit allowlist for headings, paragraphs, lists, tables, links, code, `details`, `summary`, `div`, and `span`; allow only `id`, `class`, `tabindex`, safe `data-*`, `href`, `title`, `rel`, and `aria-*` attributes and only `http`, `https`, and `mailto` protocols. Preserve heading `id` attributes so Material's table of contents continues to work. Strip scripts, event attributes, iframe/object/embed tags, and `javascript:` URLs.

In `on_page_context`, record `page.file.url -> content_hash`. In `on_post_build`, write `reader-version.json` to `site_dir`; calculate `version` as SHA-256 over sorted URL/hash pairs. Do not read or write any source after `load_source_pages()` returns.

- [ ] **Step 4: Reinstall entry points and verify plugin output**

```powershell
python -m pip install -e .
python -m unittest tests.reader.test_plugin -v
python -m unittest discover -s tests -v
```

Expected: plugin test and full suite pass; raw `.jsonl` is absent from the generated site.

- [ ] **Step 5: Commit Task 3**

```powershell
git add pyproject.toml src/jlpt_notes/reader/plugin.py tests/reader/test_plugin.py
git commit -m "feat: add JLPT MkDocs reader plugin"
```

---

### Task 4: Material Configuration and iPad Reading Assets

**Files:**
- Create: `reader/mkdocs.yml`
- Create: `reader/overrides/main.html`
- Create: `reader/assets/reader.css`
- Create: `reader/assets/reader.js`
- Modify: `tests/reader/test_plugin.py`

**Interfaces:**
- Consumes: virtual asset support and `reader-version.json` from Task 3.
- Produces: Material theme configuration, local styling, catalog filters, font controls, scroll restoration, update behavior, and Home Screen metadata.
- Produces browser storage keys `jlpt-reader-theme`, `jlpt-reader-font-scale`, `jlpt-reader-last-page`, and `jlpt-reader-scroll:<pathname>`.

- [ ] **Step 1: Extend the build test with theme and privacy assertions**

```python
def test_real_reader_config_bundles_assets_without_public_dependencies(self) -> None:
    project_root = Path(__file__).resolve().parents[2]
    config_text = (project_root / "reader/mkdocs.yml").read_text(encoding="utf-8")
    self.assertIn("name: material", config_text)
    self.assertIn("font: false", config_text)
    self.assertIn("lang:", config_text)
    self.assertIn("- ja", config_text)
    self.assertIn("- zh", config_text)
    combined = "\n".join(
        (project_root / path).read_text(encoding="utf-8")
        for path in ("reader/overrides/main.html", "reader/assets/reader.css", "reader/assets/reader.js")
    )
    self.assertNotIn("fonts.googleapis.com", combined)
    self.assertNotIn("serviceWorker.register", combined)
    self.assertIn("apple-mobile-web-app-capable", combined)
    self.assertIn("reader-version.json", combined)
```

- [ ] **Step 2: Run the focused test and confirm missing files**

```powershell
python -m unittest tests.reader.test_plugin.ReaderPluginTests.test_real_reader_config_bundles_assets_without_public_dependencies -v
```

Expected: `FileNotFoundError` for `reader/mkdocs.yml`.

- [ ] **Step 3: Add Material configuration and theme override**

```yaml
# reader/mkdocs.yml
site_name: JLPT 学习资料
site_description: 仅限家庭局域网的只读学习资料
theme:
  name: material
  language: zh
  font: false
  custom_dir: overrides
  features:
    - navigation.instant
    - navigation.sections
    - navigation.indexes
    - navigation.top
    - search.suggest
    - search.highlight
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
plugins:
  - jlpt_reader:
      assets_dir: assets
  - search:
      lang:
        - ja
        - zh
markdown_extensions:
  - admonition
  - attr_list
  - tables
  - pymdownx.details
  - pymdownx.superfences
extra_css:
  - assets/reader.css
extra_javascript:
  - assets/reader.js
repo_url: null
edit_uri: null
```

Create `reader/overrides/main.html`:

```html
{% extends "base.html" %}
{% block extrahead %}
  {{ super() }}
  <meta name="robots" content="noindex, nofollow">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <meta name="apple-mobile-web-app-title" content="JLPT 阅读">
  {% if page %}<meta name="jlpt-page-key" content="{{ page.file.url }}">{% endif %}
{% endblock %}
```

- [ ] **Step 4: Add exact reader CSS and JavaScript behavior**

The CSS must define local system font fallbacks, readable line height, metadata chips, catalog cards, filter controls, update toast, and three font scales:

```css
:root {
  --md-text-font: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic UI", "Yu Gothic", "Microsoft YaHei", sans-serif;
  --jlpt-font-scale: 1;
}
.md-typeset { font-size: calc(0.8rem * var(--jlpt-font-scale)); line-height: 1.9; }
.md-typeset p, .md-typeset li { letter-spacing: 0.01em; }
.jlpt-meta { display: flex; flex-wrap: wrap; gap: .45rem; margin: .75rem 0 1.5rem; }
.jlpt-meta-chip { border: 1px solid var(--md-default-fg-color--lightest); border-radius: 999px; padding: .18rem .6rem; color: var(--md-default-fg-color--light); }
.jlpt-reader-controls { display: flex; flex-wrap: wrap; gap: .5rem; margin: .75rem 0; }
.jlpt-reader-controls button, .jlpt-reader-controls select { min-height: 44px; padding: .35rem .7rem; }
.jlpt-catalog-entry[hidden] { display: none; }
.jlpt-update-toast { position: fixed; right: 1rem; bottom: 1rem; z-index: 20; max-width: 22rem; padding: .8rem 1rem; border-radius: .6rem; background: var(--md-primary-fg-color); color: var(--md-primary-bg-color); box-shadow: var(--md-shadow-z3); }
html[data-jlpt-font="small"] { --jlpt-font-scale: .92; }
html[data-jlpt-font="medium"] { --jlpt-font-scale: 1; }
html[data-jlpt-font="large"] { --jlpt-font-scale: 1.14; }
@media (max-width: 59.984375em) { .md-typeset { line-height: 1.82; } }
```

The JavaScript must subscribe through Material's `document$`, initialize controls after instant navigation, save scroll position before navigation, restore it once per page, filter `.jlpt-catalog-entry` elements by their data attributes, and poll `reader-version.json` every three seconds with `{cache: "no-store"}`. It must store the last non-catalog page and show a “继续上次阅读” link on the catalog instead of redirecting automatically. Implement the three explicit theme modes with this state transition:

```javascript
function applyTheme(mode) {
  const selected = ["system", "light", "dark"].includes(mode) ? mode : "system";
  localStorage.setItem("jlpt-reader-theme", selected);
  const dark = selected === "dark" ||
    (selected === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.body.setAttribute("data-md-color-scheme", dark ? "slate" : "default");
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if ((localStorage.getItem("jlpt-reader-theme") || "system") === "system") applyTheme("system");
});

function saveScrollPosition() {
  sessionStorage.setItem(`jlpt-reader-scroll:${location.pathname}`, String(window.scrollY));
}

let jlptScrollTimer;
function scheduleScrollSave() {
  window.clearTimeout(jlptScrollTimer);
  jlptScrollTimer = window.setTimeout(saveScrollPosition, 150);
}

function restoreScrollPosition() {
  const key = `jlpt-reader-scroll:${location.pathname}`;
  const value = sessionStorage.getItem(key);
  if (value !== null) requestAnimationFrame(() => window.scrollTo(0, Number(value)));
}

function applyCatalogFilters(level, type) {
  document.querySelectorAll(".jlpt-catalog-entry").forEach(entry => {
    const levelMatches = !level || entry.dataset.level === level;
    const typeMatches = !type || entry.dataset.type === type;
    entry.hidden = !(levelMatches && typeMatches);
  });
}

function showUpdateToast(message, action) {
  document.querySelector(".jlpt-update-toast")?.remove();
  const toast = document.createElement("button");
  toast.type = "button";
  toast.className = "jlpt-update-toast";
  toast.textContent = `${message}，点此刷新`;
  toast.addEventListener("click", action, { once: true });
  document.body.appendChild(toast);
}

function addSelect(container, labelText, options, selected, onChange) {
  const label = document.createElement("label");
  label.append(document.createTextNode(`${labelText} `));
  const select = document.createElement("select");
  options.forEach(([value, text]) => select.add(new Option(text, value, false, value === selected)));
  select.addEventListener("change", () => onChange(select.value));
  label.appendChild(select);
  container.appendChild(label);
}

function initializeReaderPage() {
  applyTheme(localStorage.getItem("jlpt-reader-theme") || "system");
  document.documentElement.dataset.jlptFont = localStorage.getItem("jlpt-reader-font-scale") || "medium";
  if (location.pathname !== "/") localStorage.setItem("jlpt-reader-last-page", location.pathname);
  restoreScrollPosition();
  window.removeEventListener("scroll", scheduleScrollSave);
  window.addEventListener("scroll", scheduleScrollSave, { passive: true });
  window.removeEventListener("pagehide", saveScrollPosition);
  window.addEventListener("pagehide", saveScrollPosition);
  document.querySelector(".jlpt-reader-controls")?.remove();
  const controls = document.createElement("div");
  controls.className = "jlpt-reader-controls";
  addSelect(controls, "主题", [["system", "跟随系统"], ["light", "浅色"], ["dark", "深色"]],
    localStorage.getItem("jlpt-reader-theme") || "system", applyTheme);
  addSelect(controls, "字号", [["small", "小"], ["medium", "中"], ["large", "大"]],
    localStorage.getItem("jlpt-reader-font-scale") || "medium", value => {
      localStorage.setItem("jlpt-reader-font-scale", value);
      document.documentElement.dataset.jlptFont = value;
    });
  if (location.pathname === "/") {
    let level = "", type = "";
    const levels = [...new Set([...document.querySelectorAll(".jlpt-catalog-entry")].map(node => node.dataset.level).filter(Boolean))].sort();
    const types = [...new Set([...document.querySelectorAll(".jlpt-catalog-entry")].map(node => node.dataset.type).filter(Boolean))].sort();
    addSelect(controls, "等级", [["", "全部"], ...levels.map(value => [value, value])], "", value => { level = value; applyCatalogFilters(level, type); });
    addSelect(controls, "类型", [["", "全部"], ...types.map(value => [value, value])], "", value => { type = value; applyCatalogFilters(level, type); });
    const lastPage = localStorage.getItem("jlpt-reader-last-page");
    if (lastPage && lastPage !== "/") {
      const link = document.createElement("a");
      link.href = lastPage;
      link.textContent = "继续上次阅读";
      controls.appendChild(link);
    }
  }
  document.querySelector(".md-content__inner")?.prepend(controls);
}
```

Use this update decision:

```javascript
async function checkReaderVersion() {
  const response = await fetch(new URL("/reader-version.json", window.location.origin), { cache: "no-store" });
  const next = await response.json();
  const pageKey = document.querySelector('meta[name="jlpt-page-key"]')?.content || "";
  if (!window.jlptManifest) { window.jlptManifest = next; return; }
  if (window.jlptManifest.version === next.version) return;
  const oldHash = window.jlptManifest.pages[pageKey];
  const newHash = next.pages[pageKey];
  window.jlptManifest = next;
  if (oldHash && newHash === undefined)
    showUpdateToast("当前资料已删除；返回目录后将不再显示", () => location.assign("/"));
  else if (oldHash !== newHash)
    showUpdateToast("当前资料已更新", () => location.reload());
  else {
    saveScrollPosition();
    location.reload();
  }
}
document$.subscribe(() => initializeReaderPage());
window.setInterval(() => checkReaderVersion().catch(() => {}), 3000);
```

Do not create a Service Worker. Do not import JavaScript, fonts, analytics, or CSS from a public URL.

- [ ] **Step 5: Build a fixture site and run all tests**

```powershell
python -m unittest tests.reader.test_plugin -v
python -m unittest discover -s tests -v
```

Expected: all tests pass and the built HTML references only local assets.

- [ ] **Step 6: Commit Task 4**

```powershell
git add reader/mkdocs.yml reader/overrides/main.html reader/assets/reader.css reader/assets/reader.js tests/reader/test_plugin.py
git commit -m "feat: add iPad Material reading theme"
```

---

### Task 5: Versioned Temporary Builds and Active Site Store

**Files:**
- Create: `src/jlpt_notes/reader/builder.py`
- Create: `tests/reader/test_builder.py`

**Interfaces:**
- Produces: `BuildResult(success: bool, version: str | None, error: str | None, log_path: Path | None)`.
- Produces: `build_site(source_root: Path, config_path: Path, destination: Path) -> BuildResult`.
- Produces: `SiteStore(session_root: Path)` with `current`, `activate(site_dir)`, `resolve(request_path)`, and `close()`.
- Consumes: MkDocs config and plugin from Tasks 3–4.

- [ ] **Step 1: Write failing build and atomic-switch tests**

```python
# tests/reader/test_builder.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.reader.builder import SiteStore, build_site


class ReaderBuilderTests(unittest.TestCase):
    def test_build_uses_external_destination_and_preserves_source(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            card = source / "card.md"
            card.write_text("# 卡片\n", encoding="utf-8")
            before = (card.read_bytes(), card.stat().st_mtime_ns)
            destination = base / "site"
            result = build_site(source, project / "reader/mkdocs.yml", destination)
            self.assertTrue(result.success, result.error)
            self.assertTrue((destination / "index.html").exists())
            self.assertEqual((card.read_bytes(), card.stat().st_mtime_ns), before)

    def test_site_store_keeps_previous_build_until_next_activation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, third = (root / name for name in ("site-1", "site-2", "site-3"))
            for site in (first, second, third):
                site.mkdir()
                (site / "index.html").write_text(site.name, encoding="utf-8")
            store = SiteStore(root)
            store.activate(first)
            store.activate(second)
            self.assertTrue(first.exists())
            store.activate(third)
            self.assertFalse(first.exists())
            self.assertEqual(store.resolve("/index.html"), third / "index.html")

    def test_failed_build_writes_log_beside_temporary_site_not_in_source(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            result = build_site(source, base / "missing.yml", base / "site-failed")
            self.assertFalse(result.success)
            self.assertIsNotNone(result.log_path)
            self.assertEqual(result.log_path.parent, base)
            self.assertFalse((source / "build.log").exists())
```

- [ ] **Step 2: Run the tests and verify the missing builder failure**

```powershell
python -m unittest tests.reader.test_builder -v
```

Expected: import failure for `jlpt_notes.reader.builder`.

- [ ] **Step 3: Implement MkDocs builds and active-site switching**

```python
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from threading import RLock

from mkdocs.commands.build import build
from mkdocs.config import load_config


@dataclass(frozen=True)
class BuildResult:
    success: bool
    version: str | None = None
    error: str | None = None
    log_path: Path | None = None


def build_site(source_root: Path, config_path: Path, destination: Path) -> BuildResult:
    try:
        destination.mkdir(parents=True, exist_ok=False)
        config = load_config(
            config_file=str(config_path.resolve(strict=True)),
            docs_dir=str(source_root.resolve(strict=True)),
            site_dir=str(destination.resolve()),
        )
        build(config)
        manifest = json.loads((destination / "reader-version.json").read_text(encoding="utf-8"))
        return BuildResult(True, str(manifest["version"]), None, None)
    except Exception as error:
        shutil.rmtree(destination, ignore_errors=True)
        message = f"{type(error).__name__}: {error}"
        log_path = destination.parent / f"{destination.name}.log"
        log_path.write_text(message + "\n", encoding="utf-8")
        return BuildResult(False, None, message, log_path)
```

Implement `SiteStore` with an `RLock`, one active directory, and one previous directory. `activate()` verifies `index.html`, deletes the directory older than previous, and swaps pointers while holding the lock. `resolve()` URL-decodes later in the server; here it accepts a normalized relative path, resolves it beneath the active directory, and returns only an existing regular file. `close()` clears pointers but relies on the parent `TemporaryDirectory` for final recursive cleanup. Build logs contain only the exception type and message, never page bodies or search queries; the session `TemporaryDirectory` removes them on stop.

- [ ] **Step 4: Run focused and full tests**

```powershell
python -m unittest tests.reader.test_builder -v
python -m unittest discover -s tests -v
```

Expected: all pass; source bytes and timestamps are unchanged.

- [ ] **Step 5: Commit Task 5**

```powershell
git add src/jlpt_notes/reader/builder.py tests/reader/test_builder.py
git commit -m "feat: build versioned temporary reader sites"
```

---

### Task 6: Debounced Source Change Detection

**Files:**
- Create: `src/jlpt_notes/reader/watcher.py`
- Create: `tests/reader/test_watcher.py`

**Interfaces:**
- Produces: `FileStamp(path: str, size: int, modified_ns: int)`.
- Produces: `snapshot_sources(root: Path) -> tuple[FileStamp, ...]`.
- Produces: `ChangeDetector(debounce_seconds: float)` with `observe(snapshot, now) -> bool`.
- Produces: `SourceWatcher(root, on_change, interval_seconds=1.0, debounce_seconds=0.75)` with `start()` and `stop()`.

- [ ] **Step 1: Write deterministic failing tests without sleeping**

```python
# tests/reader/test_watcher.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.reader.watcher import ChangeDetector, FileStamp, snapshot_sources


class ReaderWatcherTests(unittest.TestCase):
    def test_snapshot_tracks_only_md_and_jsonl(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_text("a", encoding="utf-8")
            (root / "b.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "c.txt").write_text("c", encoding="utf-8")
            self.assertEqual([item.path for item in snapshot_sources(root)], ["a.md", "b.jsonl"])

    def test_detector_emits_once_after_changes_stabilize(self) -> None:
        detector = ChangeDetector(debounce_seconds=0.75)
        original = (FileStamp("a.md", 1, 1),)
        changed = (FileStamp("a.md", 2, 2),)
        self.assertFalse(detector.observe(original, 0.0))
        self.assertFalse(detector.observe(changed, 1.0))
        self.assertFalse(detector.observe(changed, 1.5))
        self.assertTrue(detector.observe(changed, 1.8))
        self.assertFalse(detector.observe(changed, 2.8))
```

- [ ] **Step 2: Verify the missing watcher failure**

```powershell
python -m unittest tests.reader.test_watcher -v
```

Expected: import failure for `jlpt_notes.reader.watcher`.

- [ ] **Step 3: Implement polling and debouncing**

```python
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
import time
from typing import Callable, Iterable


@dataclass(frozen=True, order=True)
class FileStamp:
    path: str
    size: int
    modified_ns: int


def snapshot_sources(root: Path) -> tuple[FileStamp, ...]:
    resolved = root.resolve(strict=True)
    stamps = []
    for path in resolved.rglob("*"):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".md", ".jsonl"}:
            continue
        stat = path.stat()
        stamps.append(FileStamp(path.relative_to(resolved).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(sorted(stamps))
```

Implement `ChangeDetector` so the first observation establishes baseline, a changed observation starts/restarts the debounce timer, one stable observation at or after the deadline returns `True`, and identical later observations return `False`. Implement `SourceWatcher` with a daemon thread, `Event.wait(interval_seconds)` rather than `sleep`, and a caught callback exception that is sent to an optional `on_error(str)` callback instead of killing the thread.

- [ ] **Step 4: Run watcher and full tests**

```powershell
python -m unittest tests.reader.test_watcher -v
python -m unittest discover -s tests -v
```

Expected: all tests pass without timing flakes.

- [ ] **Step 5: Commit Task 6**

```powershell
git add src/jlpt_notes/reader/watcher.py tests/reader/test_watcher.py
git commit -m "feat: watch reader sources for stable changes"
```

---

### Task 7: Strictly Read-Only Static HTTP Server

**Files:**
- Create: `src/jlpt_notes/reader/server.py`
- Create: `tests/reader/test_server.py`

**Interfaces:**
- Consumes: `SiteStore.resolve()` from Task 5.
- Produces: `ReadOnlyServer(store: SiteStore, host: str, port: int)` with `start()`, `stop()`, and `bound_port`.
- Guarantees: only GET/HEAD, no directory listing, no path traversal, no raw source mapping.

- [ ] **Step 1: Write failing live-server tests on an ephemeral test port**

```python
# tests/reader/test_server.py
import urllib.error
import urllib.request
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.reader.builder import SiteStore
from jlpt_notes.reader.server import ReadOnlyServer


class ReaderServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        site = root / "site"
        site.mkdir()
        (site / "index.html").write_text("<h1>JLPT</h1>", encoding="utf-8")
        self.store = SiteStore(root)
        self.store.activate(site)
        self.server = ReadOnlyServer(self.store, "127.0.0.1", 0)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.bound_port}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temporary.cleanup()

    def test_get_and_head_work(self) -> None:
        self.assertIn("JLPT", urllib.request.urlopen(self.base + "/").read().decode())
        request = urllib.request.Request(self.base + "/", method="HEAD")
        self.assertEqual(urllib.request.urlopen(request).status, 200)

    def test_writes_and_directory_traversal_are_rejected(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            request = urllib.request.Request(self.base + "/", data=b"x", method=method)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 405)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/%2e%2e/secret.txt")
        self.assertEqual(caught.exception.code, 404)
```

- [ ] **Step 2: Run the focused tests and confirm missing server code**

```powershell
python -m unittest tests.reader.test_server -v
```

Expected: import failure for `jlpt_notes.reader.server`.

- [ ] **Step 3: Implement a generated-site-only handler**

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import PurePosixPath
from threading import Thread
from urllib.parse import unquote, urlsplit

from .builder import SiteStore


class ReadOnlyServer:
    def __init__(self, store: SiteStore, host: str, port: int) -> None:
        handler = _handler_for(store)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread = Thread(target=self._httpd.serve_forever, name="jlpt-reader-http", daemon=True)

    @property
    def bound_port(self) -> int:
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
```

Implement `_handler_for(store)` as a `BaseHTTPRequestHandler` subclass. Normalize URL paths with `urlsplit`, `unquote`, and `PurePosixPath`; reject `..`, backslashes, NUL, and absolute filesystem syntax. Map `/` and trailing slash paths to `index.html`; never list a directory. Ask `store.resolve()` for the final regular file. Set `Content-Type`, `Content-Length`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'`, and `Cache-Control: no-cache` for HTML/JSON. Material emits small inline configuration scripts, so CSP allows inline theme scripts only after Task 3 has stripped executable source HTML. `HEAD` sends identical headers without a body. Each write method returns 405 with `Allow: GET, HEAD`. Silence normal access logging and never log query strings.

- [ ] **Step 4: Run server and full tests**

```powershell
python -m unittest tests.reader.test_server -v
python -m unittest discover -s tests -v
```

Expected: all tests pass and all write methods return 405.

- [ ] **Step 5: Commit Task 7**

```powershell
git add src/jlpt_notes/reader/server.py tests/reader/test_server.py
git commit -m "feat: serve generated reader pages read-only"
```

---

### Task 8: Private Network Discovery and Explicit Firewall Setup

**Files:**
- Create: `src/jlpt_notes/reader/network.py`
- Create: `src/jlpt_notes/reader/firewall.py`
- Create: `reader/configure-firewall.ps1`
- Create: `tests/reader/test_network.py`
- Create: `tests/reader/test_firewall.py`

**Interfaces:**
- Produces: `LanAddress(interface_index: int, address: str, category: str)`.
- Produces: `parse_network_json(text: str) -> tuple[LanAddress, ...]` and `private_lan_addresses() -> tuple[LanAddress, ...]`.
- Produces: `firewall_rule_present(port: int, program_path: Path) -> bool` and `configure_firewall(script_path: Path, port: int, program_path: Path) -> bool`.
- Guarantees: rule display name `JLPT iPad Reader (Private LAN)`, profile `Private`, remote address `LocalSubnet`, TCP port `8765`, and program path exactly matching the `pythonw.exe` process that serves the reader. There is no implicit `python.exe` fallback.

- [ ] **Step 1: Write failing network and firewall contract tests**

```python
# tests/reader/test_network.py
import unittest
from jlpt_notes.reader.network import parse_network_json


class ReaderNetworkTests(unittest.TestCase):
    def test_keeps_only_private_ipv4_lan_addresses(self) -> None:
        text = '[{"InterfaceIndex":7,"IPAddress":"192.168.1.20","NetworkCategory":"Private"},{"InterfaceIndex":9,"IPAddress":"10.0.0.8","NetworkCategory":"Public"}]'
        addresses = parse_network_json(text)
        self.assertEqual([(item.interface_index, item.address) for item in addresses], [(7, "192.168.1.20")])
```

```python
# tests/reader/test_firewall.py
import unittest
from pathlib import Path


class ReaderFirewallTests(unittest.TestCase):
    def test_script_limits_access_to_private_local_subnet(self) -> None:
        project = Path(__file__).resolve().parents[2]
        script = (project / "reader/configure-firewall.ps1").read_text(encoding="utf-8")
        self.assertIn("JLPT iPad Reader (Private LAN)", script)
        self.assertIn("-Profile Private", script)
        self.assertIn("-RemoteAddress LocalSubnet", script)
        self.assertIn("-Protocol TCP", script)
        self.assertIn("-LocalPort $Port", script)
```

- [ ] **Step 2: Run both modules and verify missing implementations**

```powershell
python -m unittest tests.reader.test_network tests.reader.test_firewall -v
```

Expected: import or file-not-found failures.

- [ ] **Step 3: Implement PowerShell-backed private address discovery**

```python
# src/jlpt_notes/reader/network.py
from dataclasses import dataclass
import ipaddress
import json
import subprocess


@dataclass(frozen=True)
class LanAddress:
    interface_index: int
    address: str
    category: str


def parse_network_json(text: str) -> tuple[LanAddress, ...]:
    value = json.loads(text or "[]")
    rows = value if isinstance(value, list) else [value]
    result = []
    for row in rows:
        address = ipaddress.ip_address(str(row["IPAddress"]))
        if row.get("NetworkCategory") == "Private" and address.version == 4 and address.is_private and not address.is_loopback:
            result.append(LanAddress(int(row["InterfaceIndex"]), str(address), "Private"))
    return tuple(sorted(result, key=lambda item: (item.interface_index, item.address)))
```

Implement `private_lan_addresses()` by invoking a fixed, non-user-derived PowerShell command that joins active `Get-NetConnectionProfile` records with `Get-NetIPAddress -AddressFamily IPv4`, selects `InterfaceIndex`, `IPAddress`, and `NetworkCategory`, and emits compressed JSON. Use `subprocess.run(..., capture_output=True, text=True, timeout=10, check=True)` and pass stdout to `parse_network_json()`.

- [ ] **Step 4: Implement explicit firewall setup and status checks**

Create `configure-firewall.ps1`:

```powershell
param(
    [ValidateRange(1024,65535)][int]$Port = 8765,
    [Parameter(Mandatory = $true)][string]$Program
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Port $Port -Program `"$Program`""
    $process = Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    exit $process.ExitCode
}
$name = 'JLPT iPad Reader (Private LAN)'
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private -RemoteAddress LocalSubnet -Program $Program | Out-Null
```

Implement `firewall_rule_present()` with a fixed PowerShell query that checks the complete same-display-name rule set and accepts exactly one enabled inbound/allow/private rule with `LocalSubnet`, TCP port, and the explicitly supplied serving program. Implement `configure_firewall()` by calling the script with `-NoProfile -ExecutionPolicy Bypass -File <exact resolved script> -Port <validated int> -Program <exact resolved serving pythonw.exe>`, waiting for UAC completion, and returning `returncode == 0`. Both functions require the same explicit existing `program_path`; neither derives or defaults to `python.exe`. Never alter network category automatically.

- [ ] **Step 5: Run network, firewall, and full tests**

```powershell
python -m unittest tests.reader.test_network tests.reader.test_firewall -v
python -m unittest discover -s tests -v
```

Expected: all tests pass; tests inspect commands and parsers but do not modify the real firewall.

- [ ] **Step 6: Commit Task 8**

```powershell
git add src/jlpt_notes/reader/network.py src/jlpt_notes/reader/firewall.py reader/configure-firewall.ps1 tests/reader/test_network.py tests/reader/test_firewall.py
git commit -m "feat: restrict reader to private LAN access"
```

---

### Task 9: Reader Controller, Tkinter Launcher, CLI, and Desktop Shortcut

**Files:**
- Create: `src/jlpt_notes/reader/controller.py`
- Create: `src/jlpt_notes/reader/launcher.py`
- Modify: `src/jlpt_notes/cli.py`
- Create: `reader/install-shortcut.ps1`
- Create: `tests/reader/test_controller.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: builder, watcher, server, network, and firewall modules.
- Produces: `ReaderStatus(state, message, url)`.
- Produces: `ReaderController(root, config_path, program_path, port=8765, on_status=None)` with `start()`, `rebuild()`, `stop()`, and `configure_firewall()`.
- Produces: `launcher.run(root: Path, config_path: Path, program_path: Path, port: int = 8765) -> int`.
- Produces CLI: `python -m jlpt_notes reader --root jlpt-notes --config reader/mkdocs.yml --port 8765`.

- [ ] **Step 1: Write failing controller and CLI tests**

```python
# tests/reader/test_controller.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from jlpt_notes.reader.controller import ReaderController


class ReaderControllerTests(unittest.TestCase):
    def test_no_private_network_stays_local_and_reports_reason(self) -> None:
        with TemporaryDirectory() as directory, \
             patch("jlpt_notes.reader.controller.private_lan_addresses", return_value=()), \
             patch("jlpt_notes.reader.controller.firewall_rule_present", return_value=False):
            statuses = []
            program = Path(directory) / "pythonw.exe"
            program.write_bytes(b"test executable")
            controller = ReaderController(Path(directory), Path("reader/mkdocs.yml"), program, on_status=statuses.append)
            controller._publish_network_status()
            self.assertEqual(statuses[-1].state, "local-only")
            self.assertIn("专用网络", statuses[-1].message)

    def test_stop_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            program = Path(directory) / "pythonw.exe"
            program.write_bytes(b"test executable")
            controller = ReaderController(Path(directory), Path("reader/mkdocs.yml"), program)
            controller.stop()
            controller.stop()
```

Add to `tests/test_cli.py`:

```python
def test_cli_exposes_reader_command(self) -> None:
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    self.assertIn("reader", choices)
    args = parser.parse_args(["reader", "--root", "notes", "--config", "reader/mkdocs.yml"])
    self.assertEqual(args.port, 8765)
```

- [ ] **Step 2: Run tests and verify missing controller/command failures**

```powershell
python -m unittest tests.reader.test_controller tests.test_cli -v
```

Expected: controller import failure and missing `reader` CLI choice.

- [ ] **Step 3: Implement lifecycle orchestration**

```python
# src/jlpt_notes/reader/controller.py
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Callable

from .builder import SiteStore, build_site
from .firewall import configure_firewall, firewall_rule_present
from .network import private_lan_addresses
from .server import ReadOnlyServer
from .watcher import SourceWatcher


@dataclass(frozen=True)
class ReaderStatus:
    state: str
    message: str
    url: str | None = None


class ReaderController:
    def __init__(self, root: Path, config_path: Path, program_path: Path, port: int = 8765,
                 on_status: Callable[[ReaderStatus], None] | None = None) -> None:
        self.root = root.resolve()
        self.config_path = config_path.resolve()
        self.program_path = program_path.resolve(strict=True)
        self.port = port
        self._on_status = on_status or (lambda status: None)
        self._lock = Lock()
        self._temporary = None
        self._store = None
        self._server = None
        self._watcher = None
        self._build_number = 0
```

Implement `start()` in this order: validate root/config/port and require `program_path` to be the existing `pythonw.exe` executable actually hosting this controller; create `TemporaryDirectory(prefix="jlpt-reader-")`; create `SiteStore`; run initial build into `site-000001`; if it fails publish `error` and do not start HTTP; discover private addresses; if none or `firewall_rule_present(port, program_path)` is false, bind `127.0.0.1` and publish `local-only`; otherwise bind `0.0.0.0`, publish the first private URL, and retain all valid addresses for the launcher. Start `SourceWatcher` only after a successful site build.

Implement `rebuild()` under a nonblocking lock, build `site-NNNNNN`, activate only on success, retain the previous site on failure, and publish `running` or `error`; an error status includes the temporary `BuildResult.log_path`. Implement `stop()` as idempotent: stop watcher, stop server, close store, clean temporary directory, and publish `stopped`. Implement `_publish_network_status()` as a directly testable helper. Never invoke firewall setup automatically. The controller method `configure_firewall()` passes `self.program_path` to both the firewall configuration and status APIs; after success it stops the localhost server and restarts it on `0.0.0.0` only if a private address and the program-scoped rule are both present.

- [ ] **Step 4: Implement the Tkinter window and CLI dispatch**

The launcher window must contain status text, a selectable URL, and four buttons wired exactly as follows:

```python
copy_button = ttk.Button(frame, text="复制地址", command=copy_url)
open_button = ttk.Button(frame, text="在本机打开", command=lambda: webbrowser.open(url_var.get()))
firewall_button = ttk.Button(frame, text="配置专用网络访问", command=configure_firewall_clicked)
stop_button = ttk.Button(frame, text="停止服务", command=close_window)
window.protocol("WM_DELETE_WINDOW", close_window)
```

Start `ReaderController.start()` on a worker thread so the window remains responsive. Send status updates through `window.after(0, apply_status, status)`. `close_window` calls `controller.stop()` before destroying the window. Hide the firewall button after LAN access is active. Do not minimize to tray or remain resident after closing.

Modify `build_parser()` to add a `reader` command with `--root`, `--config`, and validated `--port`. In `main()`, dispatch `reader` before creating `Repository`, import `launcher.run` lazily, and return its code. Existing commands must remain unchanged.

`main()` must pass `Path(sys.executable).resolve()` explicitly to `launcher.run()`. The supported desktop flow starts this process through the shortcut's exact `pythonw.exe` target; `launcher.run()` and `ReaderController` verify and retain that same path. They must not silently substitute a sibling `python.exe` or another interpreter.

- [ ] **Step 5: Add the explicit desktop-shortcut installer**

```powershell
# reader/install-shortcut.ps1
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw "未找到 pythonw.exe：$pythonw" }
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'JLPT iPad 阅读器.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = "-m jlpt_notes reader --root `"$projectRoot\jlpt-notes`" --config `"$projectRoot\reader\mkdocs.yml`" --port 8765"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = '手动启动 JLPT iPad 局域网只读阅读器'
$shortcut.Save()
Write-Host "已创建：$shortcutPath"
```

The script only creates the desktop shortcut when run manually. It does not add startup entries.
The exact resolved `$pythonw` assigned to `TargetPath` is the serving executable contract consumed by the CLI, launcher, controller, firewall status check, and firewall configuration. Keep it safely quoted as one argument when passed to PowerShell.

- [ ] **Step 6: Run controller, CLI, and full tests**

```powershell
python -m unittest tests.reader.test_controller tests.test_cli -v
python -m unittest discover -s tests -v
python -m jlpt_notes --help
python -m jlpt_notes reader --help
```

Expected: tests pass; help lists the reader command and port 8765; no GUI is launched by `--help`.

- [ ] **Step 7: Commit Task 9**

```powershell
git add src/jlpt_notes/reader/controller.py src/jlpt_notes/reader/launcher.py src/jlpt_notes/cli.py reader/install-shortcut.ps1 tests/reader/test_controller.py tests/test_cli.py
git commit -m "feat: add manual Windows reader launcher"
```

---

### Task 10: End-to-End Read-Only Verification, Documentation, and iPad QA

**Files:**
- Create: `tests/reader/test_end_to_end.py`
- Modify: `README.md`
- Modify: `START-HERE.md`

**Interfaces:**
- Consumes: the complete reader stack.
- Produces: regression proof that a real build does not mutate the repository.
- Produces: user-facing start, firewall, iPad, update, and stop instructions.

- [ ] **Step 1: Write an end-to-end source immutability test**

```python
# tests/reader/test_end_to_end.py
from hashlib import sha256
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jlpt_notes.reader.builder import build_site


def repository_state(root: Path) -> dict[str, tuple[int, int, str]]:
    state = {}
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            stat = path.stat()
            state[relative] = (stat.st_size, stat.st_mtime_ns, sha256(path.read_bytes()).hexdigest())
    return state


class ReaderEndToEndTests(unittest.TestCase):
    def test_real_repository_build_is_strictly_read_only(self) -> None:
        project = Path(__file__).resolve().parents[2]
        notes = project / "jlpt-notes"
        before = repository_state(notes)
        with TemporaryDirectory() as directory:
            result = build_site(notes, project / "reader/mkdocs.yml", Path(directory) / "site")
            self.assertTrue(result.success, result.error)
        self.assertEqual(repository_state(notes), before)
```

Add fixture-level end-to-end tests that assert: formal card, nested draft, quiz question, report, malformed frontmatter, and malformed JSONL all produce readable HTML; no source extension other than generated HTML/assets/JSON appears in the site; and the manifest includes every generated page.

- [ ] **Step 2: Run end-to-end and full tests before documentation changes**

```powershell
python -m unittest tests.reader.test_end_to_end -v
python -m unittest discover -s tests -v
```

Expected: all tests pass and the real `jlpt-notes` state dictionary is identical before and after.

- [ ] **Step 3: Document the exact user workflow**

Add this concise workflow to `START-HERE.md` and a fuller troubleshooting section to `README.md`:

```markdown
## 在 iPad 阅读资料

1. 确保 Win11 和 iPad 连接同一个家庭 Wi-Fi，并将该 Windows 网络标记为“专用网络”。
2. 双击桌面的“JLPT iPad 阅读器”。首次使用时，按窗口提示配置仅限专用网络和本地子网的防火墙规则。
3. 等待状态变为“运行中”，在 iPad Safari 打开窗口显示的地址。
4. 可在 Safari 分享菜单中选择“添加到主屏幕”。
5. 阅读结束后关闭 Win11 控制窗口；地址会立即停止服务。

阅读器严格只读。它不会修改语法卡、草稿、测试、复习记录或七天复习日期。电脑休眠、关闭程序或离开当前局域网后无法访问。
```

Document these troubleshooting cases with exact symptoms and actions: public network category, missing firewall rule, different Wi-Fi/guest isolation, port 8765 conflict, computer sleep, first build error, and update-build error retaining the previous successful site.

- [ ] **Step 4: Run fresh verification and inspect generated site contents**

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python -m jlpt_notes validate --root jlpt-notes
git diff --check
```

Then build into a newly created temporary directory through `build_site()` and list generated suffixes. Expected: HTML, CSS, JavaScript, JSON, images/icons supplied by Material, and no raw `.md` or `.jsonl` files.

- [ ] **Step 5: Perform browser visual QA before touching the real firewall**

Start the reader bound to localhost, open it in a browser, and inspect at these viewport sizes:

```text
iPad portrait:  820 × 1180
iPad landscape: 1180 × 820
Small iPad:     768 × 1024
```

Verify the catalog, one formal card, one draft, one long quiz result, one JSONL page, search for Japanese/Chinese/ID/tag, light/dark themes, three font sizes, navigation collapse, scroll restoration, and update toast. Capture screenshots for comparison; fix any overflow, unreadable contrast, clipped Japanese text, or controls smaller than comfortable touch targets, then rerun the full suite.

- [ ] **Step 6: Configure the real private-LAN rule only after explicit user confirmation**

Run manually:

```powershell
$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { throw "未找到 pythonw.exe：$pythonw" }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\reader\configure-firewall.ps1 -Port 8765 -Program $pythonw
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\reader\install-shortcut.ps1
```

Expected: Windows shows an elevation confirmation for a rule scoped to the same exact `pythonw.exe` used by the desktop shortcut; the desktop shortcut is created; no startup entry is created.

- [ ] **Step 7: Perform actual iPad acceptance with the user**

Start through the desktop shortcut. Ask the user to confirm all of the following from iPad Safari on the same Wi-Fi:

```text
[ ] Address opens without a Windows or app password
[ ] Directory, search, filters, themes, and font controls work
[ ] Card titles include JLPT IDs
[ ] Drafts, tests, reports, and JSONL pages render correctly
[ ] Current-page edit shows a prompt without forced refresh
[ ] Closing the Windows control window makes the address unavailable
```

Do not claim completion until the user confirms the actual iPad checks or explicitly waives them.

- [ ] **Step 8: Commit Task 10**

```powershell
git add tests/reader/test_end_to_end.py README.md START-HERE.md
git commit -m "docs: verify and explain iPad LAN reader"
```

- [ ] **Step 9: Final branch verification**

```powershell
python -m unittest discover -s tests -v
python -m jlpt_notes validate --root jlpt-notes
git status --short
git log --oneline -10
```

Expected: all tests pass; validation succeeds; only the user's pre-existing unrelated working-tree changes remain; the ten reader tasks appear as focused commits.
