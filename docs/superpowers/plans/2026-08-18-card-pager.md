# 语法卡翻卡导航 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在正式语法卡阅读页底部输出同等级「上一张卡／下一张卡」导航（服务端渲染，经现有消毒管线）。

**Architecture:** `jlpt_reader` 插件在 `on_files` 阶段计算每张语法卡的同等级前驱/后继（最终路由 URL + 显示标题），在 `on_page_markdown` 阶段把翻卡栏 HTML 追加到页面末尾；样式加入 `reader/assets/reader.css`。增量正确性由现有 `_navigation_fingerprint` 保证，仅新增回归测试锁定。

**Tech Stack:** Python 3.10+（现有运行时）、MkDocs 插件 API、bleach 消毒、unittest。

## Global Constraints

- 不新增任何第三方依赖。
- 源资料严格只读：不读写 `jlpt-notes` 内任何文件（插件只读取既有的加载结果）。
- 所有插入 HTML 的动态文本必须经 `html.escape`；URL 用 `escape(url, quote=True)`。
- UI 文案为中文，与现有 `jlpt-*` 类命名风格一致（BEM：`jlpt-card-pager__link--prev`）。
- 测试框架沿用 unittest；下文命令中的 `<python>` 一律指 `C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`；全套测试命令：`PYTHONPATH=src <python> -m unittest discover -s tests`。
- 翻卡顺序必须复用 `_source_navigation_key`（`src/jlpt_notes/reader/plugin.py:430`），不得另写排序。
- 每个任务独立红→绿→全套→提交。

---

### Task 1: 翻卡渲染函数与消毒白名单

**Files:**
- Modify: `src/jlpt_notes/reader/plugin.py`（模块级函数区，放在 `_source_navigation_key` 之后约 `src/jlpt_notes/reader/plugin.py:443`；`_ALLOWED_TAGS` 在 `src/jlpt_notes/reader/plugin.py:444`）
- Test: `tests/reader/test_plugin.py`（新增到 `ReaderPluginTests` 类）

**Interfaces:**
- Consumes: `_sanitize_html`（`plugin.py:502`）、`_allowed_attribute`（`plugin.py:491`，已允许 `class` 和 `a` 的 `href`）。
- Produces: `_render_card_pager(previous: tuple[str, str] | None, nxt: tuple[str, str] | None) -> str`——参数是 `(URL, 显示标题)` 元组；两侧都为 `None` 返回空串；后续任务按此签名调用。

- [ ] **Step 1: 写失败测试**

在 `tests/reader/test_plugin.py` 的 `ReaderPluginTests` 类中追加（同时把 `_render_card_pager`、`_sanitize_html` 加进文件顶部的 `from jlpt_notes.reader.plugin import ...`）：

```python
    def test_card_pager_render_outputs_both_sides_with_escaped_titles(self) -> None:
        html = _render_card_pager(
            (
                "library/grammar/n4/N4-G-0001.md.__reader_markdown__/",
                "N4-G-0001｜「～までに」：截止时限",
            ),
            (
                "library/grammar/n4/N4-G-0003.md.__reader_markdown__/",
                "N4-G-0003｜「～やすい」：容易 \"与\" 易发生",
            ),
        )

        self.assertIn('<nav class="jlpt-card-pager"', html)
        self.assertIn('class="jlpt-card-pager__link jlpt-card-pager__link--prev"', html)
        self.assertIn('class="jlpt-card-pager__link jlpt-card-pager__link--next"', html)
        self.assertIn("← 上一张卡", html)
        self.assertIn("下一张卡 →", html)
        self.assertIn('href="library/grammar/n4/N4-G-0001.md.__reader_markdown__/"', html)

        cleaned = _sanitize_html(html)
        self.assertIn('jlpt-card-pager__link--prev', cleaned)
        self.assertIn('href="library/grammar/n4/N4-G-0001.md.__reader_markdown__/"', cleaned)
        self.assertIn("&quot;与&quot;", cleaned)
        self.assertNotIn("<script", cleaned)

    def test_card_pager_render_hides_missing_sides_and_empty_sequence(self) -> None:
        one_sided = _render_card_pager(None, ("library/x/", "N4-G-0002｜次"))

        self.assertNotIn("jlpt-card-pager__link--prev", one_sided)
        self.assertIn("jlpt-card-pager__link--next", one_sided)
        self.assertEqual(_render_card_pager(None, None), "")
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_plugin.ReaderPluginTests.test_card_pager_render_outputs_both_sides_with_escaped_titles tests.reader.test_plugin.ReaderPluginTests.test_card_pager_render_hides_missing_sides_and_empty_sequence -v`
Expected: FAIL，`ImportError: cannot import name '_render_card_pager'`

- [ ] **Step 3: 最小实现**

`src/jlpt_notes/reader/plugin.py`：在 `_source_navigation_key` 函数之后新增：

```python
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
```

并把 `_ALLOWED_TAGS` 集合中加入 `"nav",`（按字母序插在 `"li",` 与 `"ol",` 之间）。

- [ ] **Step 4: 运行确认通过**

Run: 同 Step 2。Expected: PASS（2 tests OK）

- [ ] **Step 5: 跑全套并提交**

```bash
git add src/jlpt_notes/reader/plugin.py tests/reader/test_plugin.py
git commit -m "feat: render grammar card pager html"
```

---

### Task 2: 同级序列计算与页面接线

**Files:**
- Modify: `src/jlpt_notes/reader/plugin.py`（`on_config` 状态初始化 `src/jlpt_notes/reader/plugin.py:49-60`、`on_files` 在 `source_files` 列表建成后 `src/jlpt_notes/reader/plugin.py:122` 附近、`on_page_markdown` 返回值 `src/jlpt_notes/reader/plugin.py:179-201`、顶部 import 加 `import posixpath`）
- Test: `tests/reader/test_plugin.py`

**Interfaces:**
- Consumes: Task 1 的 `_render_card_pager(previous, nxt)`；`_source_navigation_key(source)`；`SourcePage.metadata.level / content_type / display_title`；`File.url / File.src_uri`。
- Produces:
  - `_grammar_pager_neighbours(source_files: list[tuple[SourcePage, File]]) -> dict[str, tuple[tuple[str, str] | None, tuple[str, str] | None]]`，键为 `file.src_uri`，值为 `((prev_url, prev_title) | None, (next_url, next_title) | None)`；单卡序列与无等级/非语法卡不出现。
  - `_pager_href(target_url: str, page_url: str) -> str`——把站点根相对 URL 换算成当前页面相对 href。

- [ ] **Step 1: 写失败测试**

在 `tests/reader/test_plugin.py` 追加模块级辅助（放在 `_write_reader_config` 之后）：

```python
def _grammar_card(docs: Path, name: str, level: str | None, title: str) -> None:
    level_field = f'"level":"{level}",' if level else ""
    (docs / f"{name}.md").write_text(
        f'---\n{{"id":"{name}",{level_field}"kind":"grammar","title":"{title}"}}\n---\n\n# {title}\n\n正文。\n',
        encoding="utf-8",
    )


def _pager_section(html: str) -> str:
    match = re.search(r'<nav class="jlpt-card-pager".*?</nav>', html, flags=re.DOTALL)
    return match.group(0) if match else ""


def _page_url_of(site: Path, page: Path) -> str:
    relative = page.relative_to(site).as_posix()
    return relative.removesuffix("index.html")


def _card_page(site: Path, title: str) -> Path:
    """Locate a card's own page: it carries the body marker,目录页和邻居翻卡栏都不含正文。"""
    return next(
        p
        for p in site.rglob("*.html")
        if title in p.read_text(encoding="utf-8") and "正文。" in p.read_text(encoding="utf-8")
    )
```

再在 `ReaderPluginTests` 中追加四个测试：

```python
    def test_card_pager_links_middle_card_to_same_level_neighbours(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            _grammar_card(docs, "N4-G-0001", "N4", "第一张")
            _grammar_card(docs, "N4-G-0002", "N4", "第二张")
            _grammar_card(docs, "N4-G-0003", "N4", "第三张")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            page = _card_page(site, "第二张")
            html = page.read_text(encoding="utf-8")
            pager = _pager_section(html)
            self.assertIn("jlpt-card-pager__link--prev", pager)
            self.assertIn("jlpt-card-pager__link--next", pager)
            self.assertIn("N4-G-0001｜第一张", pager)
            self.assertIn("N4-G-0003｜第三张", pager)
            hrefs = _HrefParser()
            hrefs.feed(pager)
            resolved = {urljoin(_page_url_of(site, page), href) for href in hrefs.hrefs}
            self.assertIn("N4-G-0001.md.__reader_markdown__/", " ".join(resolved))
            self.assertIn("N4-G-0003.md.__reader_markdown__/", " ".join(resolved))

    def test_card_pager_hides_out_of_range_sides(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            _grammar_card(docs, "N4-G-0001", "N4", "第一张")
            _grammar_card(docs, "N4-G-0002", "N4", "第二张")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            first = _card_page(site, "第一张")
            last = _card_page(site, "第二张")
            self.assertNotIn("jlpt-card-pager__link--prev", _pager_section(first.read_text(encoding="utf-8")))
            self.assertIn("jlpt-card-pager__link--next", _pager_section(first.read_text(encoding="utf-8")))
            self.assertIn("jlpt-card-pager__link--prev", _pager_section(last.read_text(encoding="utf-8")))
            self.assertNotIn("jlpt-card-pager__link--next", _pager_section(last.read_text(encoding="utf-8")))

    def test_card_pager_never_crosses_levels_and_skips_levelless_cards(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            _grammar_card(docs, "N5-G-0001", "N5", "五之一")
            _grammar_card(docs, "N5-G-0002", "N5", "五之二")
            _grammar_card(docs, "N4-G-0001", "N4", "四之一")
            # 文件名不含 n[1-5] 记号且无 level 字段 → 无等级卡，不参与序列
            (docs / "broken-card.md").write_text(
                '---\n{"kind":"grammar","title":"无等级"}\n---\n\n# 无等级\n\n正文。\n',
                encoding="utf-8",
            )

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            n5_last = _card_page(site, "五之二")
            pager = _pager_section(n5_last.read_text(encoding="utf-8"))
            self.assertNotIn("jlpt-card-pager__link--next", pager)
            hrefs = _HrefParser()
            hrefs.feed(pager)
            resolved = " ".join(urljoin(_page_url_of(site, n5_last), href) for href in hrefs.hrefs)
            self.assertNotIn("N4-G-0001", resolved)
            levelless = _card_page(site, "无等级")
            self.assertEqual("", _pager_section(levelless.read_text(encoding="utf-8")))

    def test_card_pager_skips_single_card_sequence(self) -> None:
        with TemporaryDirectory() as directory:
            docs, config_file, site = _write_reader_config(Path(directory))
            _grammar_card(docs, "N3-G-0042", "N3", "孤卡")

            build(load_config(config_file=str(config_file), docs_dir=str(docs), site_dir=str(site)))

            page = _card_page(site, "孤卡")
            self.assertEqual("", _pager_section(page.read_text(encoding="utf-8")))
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_plugin.ReaderPluginTests.test_card_pager_links_middle_card_to_same_level_neighbours -v`
Expected: FAIL——页面 HTML 中找不到 `jlpt-card-pager`（`_pager_section` 返回空串导致断言失败）

- [ ] **Step 3: 最小实现**

`src/jlpt_notes/reader/plugin.py` 四处改动：

1. 顶部 import 区加一行：`import posixpath`（放在 `import json` 之后）。

2. `on_config` 状态初始化块（`self._files_by_relative_path` 之后）加：

```python
        self._pager_neighbours: dict[str, tuple[tuple[str, str] | None, tuple[str, str] | None]] = {}
```

3. `on_files` 中，`source_files.insert(0, (catalog, catalog_file))` 之后加：

```python
        self._pager_neighbours = _grammar_pager_neighbours(source_files)
```

4. `on_page_markdown` 返回语句改为（原返回值末尾追加翻卡栏）：

```python
        neighbours = self._pager_neighbours.get(page.file.src_uri)
        pager = ""
        if neighbours is not None:
            previous, nxt = neighbours
            pager = _render_card_pager(
                None if previous is None else (_pager_href(previous[0], page.file.url), previous[1]),
                None if nxt is None else (_pager_href(nxt[0], page.file.url), nxt[1]),
            )
        return (
            f"# {safe_title}\n\n{page_state}\n\n"
            f"{render_metadata_block(source.metadata)}\n\n{warning}{markdown}"
            + (f"\n\n{pager}" if pager else "")
        )
```

并在 `_render_card_pager` 之后新增两个模块级函数：

```python
def _pager_href(target_url: str, page_url: str) -> str:
    """Turn a site-root-relative URL into a href relative to the current page."""
    base = page_url if page_url.endswith("/") else posixpath.dirname(page_url)
    return posixpath.relpath(target_url, base or ".").replace("\\", "/")


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
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_plugin -v`
Expected: PASS（新增 4 项全绿，既有测试不回归）

- [ ] **Step 5: 跑全套并提交**

```bash
git add src/jlpt_notes/reader/plugin.py tests/reader/test_plugin.py
git commit -m "feat: link grammar cards with same-level pager"
```

---

### Task 3: 翻卡样式与触控契约

**Files:**
- Modify: `reader/assets/reader.css`（文件末尾追加）
- Test: `tests/reader/test_plugin.py`

**Interfaces:**
- Consumes: Task 1/2 的类名 `jlpt-card-pager`、`jlpt-card-pager__link(--prev/--next)`、`jlpt-card-pager__label`、`jlpt-card-pager__title`。
- Produces: 无代码接口；CSS 规则供静态契约测试锁定。

- [ ] **Step 1: 写失败测试**

```python
    def test_card_pager_style_contract_ships_touch_targets(self) -> None:
        css = (Path(__file__).resolve().parents[2] / "reader/assets/reader.css").read_text(encoding="utf-8")

        rule = re.search(r"\.jlpt-card-pager__link\s*\{[^}]*\}", css)
        self.assertIsNotNone(rule)
        assert rule is not None
        self.assertIn("min-height: 44px", rule.group(0))
        self.assertIn("var(--md-default-fg-color", rule.group(0))
        self.assertIn(".jlpt-card-pager__label", css)
        self.assertIn(".jlpt-card-pager__title", css)
        self.assertIn(".jlpt-card-pager__link--next", css)
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_plugin.ReaderPluginTests.test_card_pager_style_contract_ships_touch_targets -v`
Expected: FAIL——`rule` 为 None

- [ ] **Step 3: 最小实现**

`reader/assets/reader.css` 末尾追加：

```css
/* 同级语法卡翻卡栏：两格、44px 触控、明暗主题跟随 Material 变量 */
.jlpt-card-pager {
  display: flex;
  gap: 0.75rem;
  margin-top: 2.5rem;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.jlpt-card-pager__link {
  flex: 1 1 0;
  min-width: 0;
  min-height: 44px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid var(--md-default-fg-color--lightest);
  border-radius: 0.4rem;
  color: var(--md-default-fg-color);
  text-decoration: none;
}

.jlpt-card-pager__link--next {
  text-align: right;
}

.jlpt-card-pager__label {
  font-size: calc(0.8rem * var(--jlpt-font-scale));
  color: var(--md-default-fg-color--light);
}

.jlpt-card-pager__title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
```

- [ ] **Step 4: 运行确认通过**

Run: 同 Step 2。Expected: PASS

- [ ] **Step 5: 跑全套并提交**

```bash
git add reader/assets/reader.css tests/reader/test_plugin.py
git commit -m "feat: style grammar card pager for touch"
```

---

### Task 4: 增量等价回归与文档

**Files:**
- Test: `tests/reader/test_builder.py`（新增到 `ReaderBuilderTests`；复用文件顶部既有的 `TemporaryDirectory`/`Path`，另需 `import re` 与下面的 `_pager_section` 辅助）
- Modify: `README.md`（`### 日常使用` 列表末尾加一行）

**Interfaces:**
- Consumes: `build_site(source_root, config_path, destination, previous_site=...)`（`tests/reader/test_builder.py` 既有用法）；真实配置 `project / "reader/mkdocs.yml"`；Task 2 的页面输出。

- [ ] **Step 1: 写失败测试**

`tests/reader/test_builder.py` 顶部 import 加 `import re`；模块级（`ReaderBuilderTests` 类之前）加：

```python
def _pager_section(html: str) -> str:
    match = re.search(r'<nav class="jlpt-card-pager".*?</nav>', html, flags=re.DOTALL)
    return match.group(0) if match else ""


def _card(name: str, title: str, body: str = "正文。") -> str:
    return (
        f'---\n{{"id":"{name}","level":"N4","kind":"grammar","title":"{title}"}}\n---\n\n'
        f"# {title}\n\n{body}\n"
    )
```

类中追加两个测试：

```python
    def test_incremental_rebuild_after_insert_keeps_pager_equal_to_full_build(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            (source / "N4-G-0001.md").write_text(_card("N4-G-0001", "一"), encoding="utf-8")
            (source / "N4-G-0003.md").write_text(_card("N4-G-0003", "三"), encoding="utf-8")
            first = build_site(source, project / "reader/mkdocs.yml", base / "site-1")
            self.assertTrue(first.success, first.error)

            (source / "N4-G-0002.md").write_text(_card("N4-G-0002", "二"), encoding="utf-8")
            incremental = build_site(
                source, project / "reader/mkdocs.yml", base / "site-2", previous_site=base / "site-1"
            )
            self.assertTrue(incremental.success, incremental.error)
            full = build_site(source, project / "reader/mkdocs.yml", base / "site-3")
            self.assertTrue(full.success, full.error)

            for name in ("N4-G-0001", "N4-G-0002", "N4-G-0003"):
                page = f"{name}.md.__reader_markdown__/index.html"
                incremental_pager = _pager_section((base / "site-2" / page).read_text(encoding="utf-8"))
                full_pager = _pager_section((base / "site-3" / page).read_text(encoding="utf-8"))
                self.assertTrue(incremental_pager, f"{name} 缺少翻卡栏")
                self.assertEqual(incremental_pager, full_pager, name)

    def test_body_edit_incremental_reuse_keeps_neighbour_pager(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "notes"
            source.mkdir()
            (source / "N4-G-0001.md").write_text(_card("N4-G-0001", "一"), encoding="utf-8")
            (source / "N4-G-0002.md").write_text(_card("N4-G-0002", "二"), encoding="utf-8")
            first = build_site(source, project / "reader/mkdocs.yml", base / "site-1")
            self.assertTrue(first.success, first.error)

            (source / "N4-G-0002.md").write_text(_card("N4-G-0002", "二", "改后的正文。"), encoding="utf-8")
            incremental = build_site(
                source, project / "reader/mkdocs.yml", base / "site-2", previous_site=base / "site-1"
            )
            self.assertTrue(incremental.success, incremental.error)
            self.assertGreaterEqual(incremental.reused_pages, 1)

            reused = (base / "site-2" / "N4-G-0001.md.__reader_markdown__/index.html").read_text(encoding="utf-8")
            pager = _pager_section(reused)
            self.assertIn("N4-G-0002｜二", pager)
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_builder.ReaderBuilderTests.test_incremental_rebuild_after_insert_keeps_pager_equal_to_full_build -v`
Expected: FAIL——`N4-G-0001 缺少翻卡栏`（若 Task 1-3 未完成则先完成它们；本任务验证的是既有增量机制与新功能的组合）

- [ ] **Step 3: 验证测试通过（本任务无产品代码改动）**

Run: `PYTHONPATH=src <python> -m unittest tests.reader.test_builder -v`
Expected: PASS

- [ ] **Step 4: 更新 README**

`README.md` 的 `### 日常使用` 有序列表末尾加：

```markdown
6. 正式语法卡的页尾提供「上一张卡／下一张卡」，仅在同级序列内按编号顺序翻阅；序列首尾自动隐藏对应按钮。
```

- [ ] **Step 5: 跑全套并提交**

```bash
git add tests/reader/test_builder.py README.md
git commit -m "test: lock incremental card pager equivalence"
```

---

## 验收（实施完成后）

在真实资料库上抽查 N4 序列第一张、中间一张、最后一张的页面（用现有 `build_site` 手工构建后检查 HTML），确认翻卡栏与侧边栏目录顺序一致、首尾隐藏，并保持 `jlpt-notes` 哈希不变。
