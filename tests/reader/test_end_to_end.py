from hashlib import sha256
from html import unescape
import http.client
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from jlpt_notes.reader.builder import SiteStore, build_site
from jlpt_notes.reader.server import ReadOnlyServer
from jlpt_notes.reader.submissions import apply_submission


def repository_state(root: Path) -> dict[str, tuple[int, int, str]]:
    """Capture enough state to prove that reader operations did not write."""
    state: dict[str, tuple[int, int, str]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            stat = path.stat()
            state[relative] = (
                stat.st_size,
                stat.st_mtime_ns,
                sha256(path.read_bytes()).hexdigest(),
            )
    return state


def _write_fixture_library(root: Path) -> None:
    files = {
        "grammar/N5-G-0001.md": (
            '---\n{"id":"N5-G-0001","level":"N5","kind":"grammar",'
            '"title":"～です","tags":["判断"]}\n---\n\n# 核心\n正式卡正文\n'
        ),
        "drafts/nested/proposal.md": (
            '---\n{"id":"N2-D-0007","level":"N2","kind":"draft",'
            '"title":"～わけではない"}\n---\n\n# 草稿\n嵌套草稿正文\n'
        ),
        "quizzes/questions/N2-Q-0003.md": (
            '---\n{"id":"N2-Q-0003","level":"N2","kind":"quiz-question",'
            '"title":"四选一"}\n---\n\n# 问题\n测试题正文\n'
        ),
        "quizzes/results/2026-08-18.md": (
            '---\n{"level":"N2","kind":"quiz-result","title":"测试报告"}\n---\n\n'
            "# 结果\n长测试报告正文\n"
        ),
        "broken/frontmatter.md": "---\nnot-json\n---\n\n# 仍可阅读\n损坏元数据正文\n",
        "history/events.jsonl": (
            '{"id":"event-1","status":"ok","result":"保留"}\n'
            "{this line is malformed}\n"
        ),
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _request(port: int, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def _route_containing(site: Path, text: str) -> str:
    for page in site.rglob("index.html"):
        if text in page.read_text(encoding="utf-8"):
            relative = page.relative_to(site).as_posix()
            return "/" if relative == "index.html" else f"/{relative.removesuffix('index.html')}"
    raise AssertionError(f"No generated page contains {text!r}")


class ReaderEndToEndTests(unittest.TestCase):
    def test_user_docs_require_one_stable_same_runtime_install_chain(self) -> None:
        project = Path(__file__).resolve().parents[2]
        readme = (project / "README.md").read_text(encoding="utf-8")

        self.assertIn(r"D:\PersonalProject\n5-n2-n1-1-2-3", readme)
        self.assertIn("安装阅读器（稳定目录）", readme)
        self.assertIn("创建桌面快捷方式", readme)
        self.assertIn("Private + LocalSubnet", readme)
        self.assertIn("python.exe", readme)
        self.assertIn("pythonw.exe", readme)
        self.assertIn(".worktrees", readme)
        self.assertIn("重新安装", readme)
        self.assertNotIn("首次设置包含两项", readme)

    def test_committed_repository_build_is_strictly_read_only(self) -> None:
        project = Path(__file__).resolve().parents[2]
        notes = project / "jlpt-notes"
        before = repository_state(notes)
        with TemporaryDirectory() as directory:
            result = build_site(
                notes,
                project / "reader/mkdocs.yml",
                Path(directory) / "site",
            )
            self.assertTrue(result.success, result.error)
        self.assertEqual(repository_state(notes), before)

    def test_fixture_library_renders_every_supported_page_without_source_artifacts(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            notes = base / "notes"
            notes.mkdir()
            _write_fixture_library(notes)
            before = repository_state(notes)

            result = build_site(notes, project / "reader/mkdocs.yml", base / "site")

            self.assertTrue(result.success, result.error)
            self.assertEqual(repository_state(notes), before)
            site = base / "site"
            rendered = "\n".join(
                unescape(path.read_text(encoding="utf-8"))
                for path in site.rglob("*.html")
            )
            for text in (
                "N5-G-0001｜～です",
                "正式卡正文",
                "N2-D-0007｜草稿｜～わけではない",
                "嵌套草稿正文",
                "N2-Q-0003｜四选一",
                "测试题正文",
                "测试报告",
                "长测试报告正文",
                "损坏元数据正文",
                "元数据无法解析",
                "event-1",
                "第 2 行无法解析",
            ):
                self.assertIn(text, rendered)

            manifest = json.loads(
                (site / "reader-version.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["pages"]), len(before) + 1)
            for route in manifest["pages"]:
                self.assertTrue((site / route / "index.html").is_file(), route)
            self.assertFalse(list(site.rglob("*.md")))
            self.assertFalse(list(site.rglob("*.jsonl")))
            self.assertFalse((notes / "site").exists())
            self.assertFalse((notes / "reader-version.json").exists())

    def test_real_http_boundary_serves_get_and_head_and_rejects_all_writes(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            notes = base / "notes"
            notes.mkdir()
            _write_fixture_library(notes)
            before = repository_state(notes)
            session = base / "session"
            session.mkdir()
            result = build_site(notes, project / "reader/mkdocs.yml", session / "site-1")
            self.assertTrue(result.success, result.error)
            store = SiteStore(session)
            store.activate(session / "site-1")
            server = ReadOnlyServer(store, "127.0.0.1", 0)
            server.start()
            port = server.bound_port
            try:
                get_status, get_headers, get_body = _request(port, "GET", "/")
                head_status, head_headers, head_body = _request(port, "HEAD", "/")
                self.assertEqual(get_status, 200)
                self.assertIn("JLPT", get_body.decode("utf-8"))
                self.assertEqual(head_status, 200)
                self.assertEqual(head_body, b"")
                self.assertEqual(head_headers["Content-Length"], get_headers["Content-Length"])
                for method in ("POST", "PUT", "PATCH", "DELETE", "MKCOL", "MOVE"):
                    status, headers, body = _request(port, method, "/")
                    self.assertEqual(status, 405, method)
                    self.assertEqual(headers["Allow"], "GET, HEAD")
                    self.assertEqual(body, b"")
                self.assertEqual(repository_state(notes), before)
            finally:
                server.stop()
                store.close()

            with self.assertRaises((ConnectionRefusedError, OSError)):
                _request(port, "GET", "/")

    def test_update_switches_generations_and_failed_update_keeps_last_good(self) -> None:
        project = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            base = Path(directory)
            notes = base / "notes"
            notes.mkdir()
            _write_fixture_library(notes)
            session = base / "session"
            session.mkdir()
            first = build_site(notes, project / "reader/mkdocs.yml", session / "site-1")
            self.assertTrue(first.success, first.error)
            store = SiteStore(session)
            store.activate(session / "site-1")
            server = ReadOnlyServer(store, "127.0.0.1", 0)
            server.start()
            try:
                card = notes / "grammar/N5-G-0001.md"
                card.write_text(card.read_text(encoding="utf-8") + "\n更新后正文\n", encoding="utf-8")
                expected_after_edit = repository_state(notes)
                second = build_site(notes, project / "reader/mkdocs.yml", session / "site-2")
                self.assertTrue(second.success, second.error)
                self.assertEqual(repository_state(notes), expected_after_edit)
                store.activate(session / "site-2")
                route = _route_containing(session / "site-2", "更新后正文")
                status, _, body = _request(server.bound_port, "GET", route)
                self.assertEqual(status, 200)
                self.assertIn("更新后正文", body.decode("utf-8"))

                card.write_bytes(b"\xffinvalid utf-8")
                expected_broken_state = repository_state(notes)
                failed = build_site(notes, project / "reader/mkdocs.yml", session / "site-3")
                self.assertFalse(failed.success)
                self.assertEqual(repository_state(notes), expected_broken_state)
                status, _, body = _request(server.bound_port, "GET", route)
                self.assertEqual(status, 200)
                self.assertIn("更新后正文", body.decode("utf-8"))
                self.assertFalse((session / "site-3").exists())
                self.assertTrue(failed.log_path and failed.log_path.is_file())
            finally:
                server.stop()
                store.close()


_SUBMISSION_PAPER = """# 测试卷

## 作答说明

- 每题只有一个最佳答案。

## 第一部分：形式选择（1–2）

### 1. 問題一（　）。

1. 甲
2. 乙
3. 丙
4. 丁

### 2. 問題二（　）。

1. 甲
2. 乙
3. 丙
4. 丁

## 第二部分：排序（3）

### 3. 昨日、＿＿ ★ ＿＿ ＿＿ 話しました。

1. 先輩が
2. 教えてくれた
3. 店について
4. 友だちに

## 答案填写区

```text
第一部分（1–2）：
_1_ , _1_

第二部分（3，请提交完整语序，如“3：1234”）：
_1_
```
"""


def _quiz_state_of(page_html: str) -> dict:
    match = re.search(r'data-quiz-state="([^"]+)"', page_html)
    assert match, "page is missing quiz state"
    return json.loads(unescape(match.group(1)))


class QuizSubmissionEndToEndTests(unittest.TestCase):
    def test_submit_updates_the_paper_and_the_page_turns_read_only(self) -> None:
        project = Path(__file__).resolve().parents[2]
        payload = json.dumps({
            "paper": "paper.md",
            "answers": [
                {"number": 1, "value": "1", "uncertain": False},
                {"number": 2, "value": "3", "uncertain": True},
                {"number": 3, "value": "2314", "uncertain": False},
            ],
        }).encode("utf-8")
        with TemporaryDirectory() as directory:
            base = Path(directory)
            notes = base / "notes"
            papers = notes / "quizzes" / "papers"
            papers.mkdir(parents=True)
            (papers / "paper.md").write_text(_SUBMISSION_PAPER, encoding="utf-8")
            grammar = notes / "grammar"
            grammar.mkdir()
            (grammar / "N5-G-0001.md").write_text(
                '---\n{"id":"N5-G-0001","level":"N5","kind":"grammar",'
                '"title":"～です","tags":["判断"]}\n---\n\n# 核心\n正式卡正文\n',
                encoding="utf-8",
            )
            before = repository_state(notes)
            session = base / "session"
            session.mkdir()
            first = build_site(notes, project / "reader/mkdocs.yml", session / "site-1")
            self.assertTrue(first.success, first.error)
            route = _route_containing(session / "site-1", "問題一")
            store = SiteStore(session)
            store.activate(session / "site-1")

            def submit(body: bytes):
                result = apply_submission(papers, body)
                return result.status_code, result.body

            server = ReadOnlyServer(store, "127.0.0.1", 0, submit=submit)
            server.start()
            port = server.bound_port
            try:
                status, _, body = _request(port, "GET", route)
                self.assertEqual(status, 200)
                page = body.decode("utf-8")
                self.assertEqual(_quiz_state_of(page)["answered"], False)

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("POST", "/reader/submit-answers", body=payload)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                connection.close()

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("POST", "/reader/submit-answers", body=payload)
                response = connection.getresponse()
                self.assertEqual(response.status, 409)
                connection.close()

                saved = (papers / "paper.md").read_text(encoding="utf-8")
                self.assertIn("1-1 , *2-3", saved)
                self.assertIn("3-2314", saved)

                second = build_site(notes, project / "reader/mkdocs.yml", session / "site-2")
                self.assertTrue(second.success, second.error)
                store.activate(session / "site-2")
                status, _, body = _request(port, "GET", route)
                self.assertEqual(status, 200)
                page = body.decode("utf-8")
                self.assertEqual(_quiz_state_of(page)["answered"], True)
                self.assertIn("1-1 , *2-3", unescape(page))

                after = repository_state(notes)
                changed = {path for path in after if after[path] != before.get(path)}
                self.assertEqual(changed, {"quizzes/papers/paper.md"})
            finally:
                server.stop()
                store.close()


if __name__ == "__main__":
    unittest.main()
