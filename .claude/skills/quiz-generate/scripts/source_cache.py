"""日本語NET 题源证据缓存。

只缓存最终采用页面的原始摘录；搜索结果 JSON 不属于证据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ALLOWED_HOSTS = {"nihongokyoshi-net.com", "www.nihongokyoshi-net.com"}
CACHE_REL = Path("quizzes/sources/cache")
INDEX_NAME = "index.json"
GRAMMAR_RE = re.compile(r"^[NS][1-5]-G-\d{4}$")

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def canonical_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise ValueError("题源网址必须属于日本語NET（nihongokyoshi-net.com）")
    host = "nihongokyoshi-net.com"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") + "/"
    return urlunsplit(("https", host, path, parts.query, ""))


def parse_day(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD") from exc


def cache_dir(notes_root: Path) -> Path:
    return notes_root / CACHE_REL


def load_index(notes_root: Path) -> dict:
    path = cache_dir(notes_root) / INDEX_NAME
    if not path.exists():
        return {"schema_version": 1, "sources": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("sources"), dict):
        raise ValueError(f"缓存索引格式无效：{path}")
    return data


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def source_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def add_source(args) -> int:
    notes_root = Path(args.root).resolve()
    evidence = Path(args.evidence).resolve()
    if not evidence.is_file():
        raise ValueError(f"证据文件不存在：{evidence}")
    lower_name = evidence.name.lower()
    if evidence.suffix.lower() == ".json" or "search" in lower_name:
        raise ValueError("搜索结果 JSON／搜索输出不能作为题源证据")
    raw = evidence.read_bytes()
    if not raw:
        raise ValueError("证据摘录不能为空")
    suffix = evidence.suffix.lower()
    allowed_suffixes = {".md", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
    if suffix not in allowed_suffixes:
        raise ValueError("证据只接受 Markdown、文本或 PNG/JPEG/WebP 截图")
    if suffix in {".md", ".txt"}:
        body = raw.decode("utf-8").strip()
        if not body:
            raise ValueError("证据摘录不能为空")
        raw = (body + "\n").encode("utf-8")
        max_bytes = 100_000
    else:
        max_bytes = 5_000_000
    if len(raw) > max_bytes:
        raise ValueError("证据过大；只保留足以复核的原始摘录或截图")
    url = canonical_url(args.url)
    accessed = parse_day(args.accessed_at).isoformat()
    grammars = sorted(set(args.grammar or []))
    bad = [g for g in grammars if not GRAMMAR_RE.fullmatch(g)]
    if bad:
        raise ValueError(f"语法卡号格式无效：{', '.join(bad)}")
    key = source_key(url)
    for label, value in (("title", args.title), ("publisher", args.publisher), ("locator", args.locator)):
        if not value.strip():
            raise ValueError(f"{label} 不能为空")
    digest = hashlib.sha256(raw).hexdigest()
    target_dir = cache_dir(notes_root)
    target = target_dir / f"{key}-{digest[:12]}{suffix}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)

    index = load_index(notes_root)
    index["sources"][key] = {
        "site_name": "日本語NET",
        "url": url,
        "title": args.title.strip(),
        "publisher": args.publisher.strip(),
        "accessed_at": accessed,
        "grammar_ids": grammars,
        "locator": args.locator.strip(),
        "evidence_path": (CACHE_REL / target.name).as_posix(),
        "content_sha256": digest,
    }
    atomic_json(target_dir / INDEX_NAME, index)
    print(json.dumps({"key": key, **index["sources"][key]}, ensure_ascii=False, indent=2))
    return 0


def verify_record(notes_root: Path, key: str, record: dict) -> list[str]:
    errors: list[str] = []
    try:
        expected_key = source_key(canonical_url(str(record.get("url", ""))))
        if expected_key != key:
            errors.append(f"{key}: key 与 URL 不匹配")
    except ValueError as exc:
        errors.append(f"{key}: {exc}")
    if record.get("site_name") != "日本語NET":
        errors.append(f"{key}: site_name 必须是日本語NET")
    try:
        parse_day(str(record.get("accessed_at", "")))
    except ValueError as exc:
        errors.append(f"{key}: {exc}")
    rel = Path(str(record.get("evidence_path", "")))
    if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() == ".json":
        errors.append(f"{key}: evidence_path 非法")
        return errors
    path = notes_root / rel
    if not path.is_file():
        errors.append(f"{key}: 证据文件不存在：{rel.as_posix()}")
        return errors
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record.get("content_sha256"):
        errors.append(f"{key}: 证据哈希不匹配")
    return errors


def verify(args) -> int:
    notes_root = Path(args.root).resolve()
    index = load_index(notes_root)
    errors = []
    for key, record in sorted(index["sources"].items()):
        errors.extend(verify_record(notes_root, key, record))
    if errors:
        for error in errors:
            print(f"[错误] {error}")
        print(f"缓存校验失败：{len(errors)} 个问题")
        return 1
    print(f"缓存校验通过：{len(index['sources'])} 个日本語NET页面")
    return 0


def lookup(args) -> int:
    notes_root = Path(args.root).resolve()
    index = load_index(notes_root)
    wanted_url = canonical_url(args.url) if args.url else None
    today = parse_day(args.today) if args.today else datetime.now(timezone.utc).date()
    matches = []
    for key, record in sorted(index["sources"].items()):
        if wanted_url and record.get("url") != wanted_url:
            continue
        if args.grammar and args.grammar not in record.get("grammar_ids", []):
            continue
        age = (today - parse_day(record["accessed_at"])).days
        item = {"key": key, "age_days": age, "fresh": 0 <= age <= args.max_age_days, **record}
        matches.append(item)
    print(json.dumps(matches, ensure_ascii=False, indent=2))
    return 0 if any(item["fresh"] for item in matches) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="日本語NET 题源证据缓存")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="加入最终采用页面的证据摘录")
    add.add_argument("--root", required=True, help="jlpt-notes 目录")
    add.add_argument("--url", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--publisher", required=True)
    add.add_argument("--accessed-at", required=True)
    add.add_argument("--grammar", action="append", default=[])
    add.add_argument("--locator", required=True)
    add.add_argument("--evidence", required=True)
    add.set_defaults(func=add_source)

    check = sub.add_parser("verify", help="校验证据文件与索引哈希")
    check.add_argument("--root", required=True)
    check.set_defaults(func=verify)

    find = sub.add_parser("lookup", help="按 URL 或语法卡查缓存")
    find.add_argument("--root", required=True)
    group = find.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--grammar")
    find.add_argument("--max-age-days", type=int, default=90)
    find.add_argument("--today", help="测试或复现用日期，默认今天")
    find.set_defaults(func=lookup)
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
