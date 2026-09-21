import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "source_cache.py"


def run_cache(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", check=False)


def test_add_lookup_and_verify_japanese_net_source(tmp_path):
    notes = tmp_path / "jlpt-notes"
    evidence = tmp_path / "selected.md"
    evidence.write_text("## 例文\n日本語NETから実際に保存した抜粋。\n", encoding="utf-8")
    result = run_cache(
        "add", "--root", notes,
        "--url", "https://www.nihongokyoshi-net.com/example",
        "--title", "例文ページ", "--publisher", "日本語NET／ノッチ",
        "--accessed-at", "2026-09-21", "--grammar", "N3-G-0001",
        "--locator", "例文区", "--evidence", evidence,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    added = json.loads(result.stdout)
    assert added["site_name"] == "日本語NET"
    assert added["url"] == "https://nihongokyoshi-net.com/example/"

    verified = run_cache("verify", "--root", notes)
    assert verified.returncode == 0, verified.stdout + verified.stderr

    found = run_cache(
        "lookup", "--root", notes, "--grammar", "N3-G-0001",
        "--today", "2026-10-01", "--max-age-days", "90",
    )
    assert found.returncode == 0
    assert json.loads(found.stdout)[0]["fresh"] is True


def test_rejects_other_site_and_search_json(tmp_path):
    notes = tmp_path / "jlpt-notes"
    evidence = tmp_path / "selected.md"
    evidence.write_text("evidence", encoding="utf-8")
    other = run_cache(
        "add", "--root", notes, "--url", "https://example.com/page",
        "--title", "x", "--publisher", "x", "--accessed-at", "2026-09-21",
        "--locator", "x", "--evidence", evidence,
    )
    assert other.returncode == 1
    assert "日本語NET" in other.stderr

    search = tmp_path / "search1.json"
    search.write_text("{}", encoding="utf-8")
    raw = run_cache(
        "add", "--root", notes,
        "--url", "https://nihongokyoshi-net.com/page/",
        "--title", "x", "--publisher", "x", "--accessed-at", "2026-09-21",
        "--locator", "x", "--evidence", search,
    )
    assert raw.returncode == 1
    assert "搜索结果" in raw.stderr
