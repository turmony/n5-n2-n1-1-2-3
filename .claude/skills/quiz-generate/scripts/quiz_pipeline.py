"""结构化试卷草稿的预检、增量审题状态与三件套渲染。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

LEVEL_RE = re.compile(r"^N[1-5]$")
CARD_RE = re.compile(r"^(N[1-5])-Q-(\d{4})$")
GRAMMAR_RE = re.compile(r"^N[1-5]-G-\d{4}$")
SLUG_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
SECTIONS = ("form", "order", "cloze")
SECTION_LABELS = {
    "form": "第一部分：文の文法１（形式选择）",
    "order": "第二部分：句子排序",
    "cloze": "第三部分：篇章完形",
}
ALLOWED_HOSTS = {"nihongokyoshi-net.com", "www.nihongokyoshi-net.com"}
PHASES = {
    "selection", "search", "scrape", "draft", "preflight",
    "blind_review", "revision", "render", "validation",
}

for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("draft 顶层必须是 JSON 对象")
    return data


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def atomic_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body.rstrip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def source_errors(source: dict, notes_root: Path, prefix: str) -> list[str]:
    errors = []
    if not isinstance(source, dict):
        return [f"{prefix}.source 必须是对象"]
    if source.get("site_name") != "日本語NET":
        errors.append(f"{prefix}.source.site_name 必须是日本語NET")
    for field in ("publisher", "title", "url", "locator", "accessed_at"):
        if not nonempty(source.get(field)):
            errors.append(f"{prefix}.source.{field} 不能为空")
    host = (urlsplit(str(source.get("url", ""))).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        errors.append(f"{prefix}.source.url 必须属于 nihongokyoshi-net.com")
    try:
        date.fromisoformat(str(source.get("accessed_at", "")))
    except ValueError:
        errors.append(f"{prefix}.source.accessed_at 必须是 YYYY-MM-DD")
    paths = source.get("evidence_paths")
    if not isinstance(paths, list) or not paths:
        errors.append(f"{prefix}.source.evidence_paths 至少需要一项")
    else:
        for raw in paths:
            rel = Path(str(raw))
            lower = rel.name.lower()
            if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() == ".json" or "search" in lower:
                errors.append(f"{prefix}.source.evidence_paths 禁止搜索 JSON 或越界路径：{raw}")
                continue
            path = notes_root / rel
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"{prefix}.source 证据不存在或为空：{raw}")
    kind = source.get("kind")
    if kind == "derived_from_example":
        for field in ("original_example", "answer_basis"):
            if not nonempty(source.get(field)):
                errors.append(f"{prefix}.source.{field} 不能为空")
        if not isinstance(source.get("transformations"), list) or not source["transformations"]:
            errors.append(f"{prefix}.source.transformations 至少需要一项")
        if not isinstance(source.get("distractor_basis"), list) or len(source["distractor_basis"]) != 4:
            errors.append(f"{prefix}.source.distractor_basis 必须逐项记录四项依据")
    elif kind == "teaching_exercise":
        for field in ("answer_locator", "original_answer", "option_mapping", "adaptation"):
            if source.get(field) in (None, "", [], {}):
                errors.append(f"{prefix}.source.{field} 不能为空")
        if source.get("answer_url"):
            answer_host = (urlsplit(str(source["answer_url"])).hostname or "").lower()
            if answer_host not in ALLOWED_HOSTS:
                errors.append(f"{prefix}.source.answer_url 必须属于 nihongokyoshi-net.com")
    else:
        errors.append(f"{prefix}.source.kind 只能是 teaching_exercise 或 derived_from_example")
    return errors


def question_errors(q: dict, notes_root: Path, stage: str) -> list[str]:
    qid = str(q.get("id", "<无ID>"))
    prefix = f"题卡 {qid}"
    errors = []
    match = CARD_RE.fullmatch(qid)
    if not match:
        errors.append(f"{prefix}.id 格式无效")
    if not isinstance(q.get("number"), int) or q["number"] < 1:
        errors.append(f"{prefix}.number 必须是正整数")
    if not isinstance(q.get("revision"), int) or not 1 <= q["revision"] <= 3:
        errors.append(f"{prefix}.revision 必须为 1–3（最多两轮修订）")
    if q.get("section") not in SECTIONS:
        errors.append(f"{prefix}.section 必须是 form/order/cloze")
    for field in ("item_type", "prompt", "translation", "conjugation", "correct_explanation"):
        if not nonempty(q.get(field)):
            errors.append(f"{prefix}.{field} 不能为空")
    tested = q.get("tested_cards")
    if not isinstance(tested, list) or not tested or any(not GRAMMAR_RE.fullmatch(str(x)) for x in tested):
        errors.append(f"{prefix}.tested_cards 必须包含合法语法卡号")
    options = q.get("options")
    if not isinstance(options, dict) or set(options) != set("1234") or any(not nonempty(v) for v in options.values()):
        errors.append(f"{prefix}.options 必须有非空的 1–4 四项")
    correct = str(q.get("correct_option", ""))
    if correct not in set("1234"):
        errors.append(f"{prefix}.correct_option 必须是 1–4")
    explanations = q.get("option_explanations")
    if not isinstance(explanations, dict) or set(explanations) != set("1234") or any(not nonempty(v) for v in explanations.values()):
        errors.append(f"{prefix}.option_explanations 必须完整解释 1–4 四项")
    if q.get("section") == "order":
        order = str(q.get("recommended_order", ""))
        if sorted(order) != list("1234"):
            errors.append(f"{prefix}.recommended_order 必须是 1–4 的排列")
    preflight = q.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "passed":
        errors.append(f"{prefix}.preflight.status 必须为 passed")
    else:
        for field in ("surface_connection", "semantic_exclusion", "unique_answer_rationale"):
            if not nonempty(preflight.get(field)):
                errors.append(f"{prefix}.preflight.{field} 不能为空")
    errors.extend(source_errors(q.get("source"), notes_root, prefix))
    if stage == "final":
        review = q.get("review")
        if not isinstance(review, dict):
            errors.append(f"{prefix}.review 必须记录独立审题")
        else:
            for name in ("blind", "source"):
                item = review.get(name)
                if not isinstance(item, dict) or item.get("status") != "passed":
                    errors.append(f"{prefix}.review.{name}.status 必须为 passed")
                    continue
                if item.get("reviewed_revision") != q.get("revision"):
                    errors.append(f"{prefix}.review.{name} 版本落后于当前 revision")
                for field in ("reviewer", "reviewed_at", "notes"):
                    if not nonempty(item.get(field)):
                        errors.append(f"{prefix}.review.{name}.{field} 不能为空")
            blind = review.get("blind", {})
            if str(blind.get("answer", "")) != correct:
                errors.append(f"{prefix}.review.blind.answer 与标准答案不一致")
    return errors


def validate_data(data: dict, repo_root: Path, stage: str) -> list[str]:
    errors = []
    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    quiz = data.get("quiz")
    if not isinstance(quiz, dict):
        return errors + ["quiz 必须是对象"]
    for field in ("slug", "title", "date", "level"):
        if not nonempty(quiz.get(field)):
            errors.append(f"quiz.{field} 不能为空")
    if quiz.get("slug") and not SLUG_RE.fullmatch(str(quiz["slug"])):
        errors.append("quiz.slug 必须形如 YYYY-MM-DD-n3-topic-test-1")
    if quiz.get("level") and not LEVEL_RE.fullmatch(str(quiz["level"])):
        errors.append("quiz.level 必须是 N5–N1")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        return errors + ["questions 至少需要一题"]
    notes_root = repo_root / "jlpt-notes"
    ids = [str(q.get("id", "")) for q in questions]
    numbers = [q.get("number") for q in questions]
    if len(ids) != len(set(ids)):
        errors.append("题卡 ID 重复")
    if sorted(n for n in numbers if isinstance(n, int)) != list(range(1, len(questions) + 1)):
        errors.append("题号必须从 1 连续编号")
    prompts = [re.sub(r"\s+", "", str(q.get("prompt", ""))) for q in questions]
    if len(prompts) != len(set(prompts)):
        errors.append("draft 内存在完全重复题干")
    section_order = [SECTIONS.index(q.get("section")) for q in questions if q.get("section") in SECTIONS]
    if section_order != sorted(section_order):
        errors.append("题目必须按 form、order、cloze 的分区顺序排列")
    numeric = []
    for q in questions:
        errors.extend(question_errors(q, notes_root, stage))
        match = CARD_RE.fullmatch(str(q.get("id", "")))
        if match:
            if match.group(1) != quiz.get("level"):
                errors.append(f"题卡 {q['id']} 与 quiz.level 不一致")
            numeric.append(int(match.group(2)))
    if numeric and sorted(numeric) != list(range(min(numeric), min(numeric) + len(numeric))):
        errors.append("新题卡编号必须连续")
    return errors


def template_data() -> dict:
    return {
        "schema_version": 1,
        "quiz": {
            "slug": "2026-01-01-n3-topic-test-1",
            "title": "N3 语法练习",
            "date": "2026-01-01",
            "level": "N3",
            "suggested_minutes": 10,
        },
        "questions": [{
            "number": 1,
            "id": "N3-Q-0001",
            "revision": 1,
            "section": "form",
            "item_type": "form_choice",
            "prompt": "例句（　）。",
            "translation": "翻译。",
            "tested_cards": ["N3-G-0001"],
            "conjugation": "正确接续。",
            "options": {"1": "选项一", "2": "选项二", "3": "选项三", "4": "选项四"},
            "correct_option": "1",
            "correct_explanation": "正确项理由。",
            "option_explanations": {"1": "正确。", "2": "错误理由。", "3": "错误理由。", "4": "错误理由。"},
            "source": {
                "kind": "derived_from_example",
                "site_name": "日本語NET",
                "publisher": "已核实运营者",
                "title": "页面标题",
                "url": "https://nihongokyoshi-net.com/example/",
                "locator": "例文区定位",
                "accessed_at": "2026-01-01",
                "evidence_paths": ["quizzes/sources/cache/证据.md"],
                "original_example": "来源原例句。",
                "transformations": ["挖空目标语法。"],
                "answer_basis": "来源讲解与语法卡。",
                "distractor_basis": ["1. 正确项依据", "2. 干扰项依据", "3. 干扰项依据", "4. 干扰项依据"],
            },
            "preflight": {
                "status": "pending",
                "surface_connection": "",
                "semantic_exclusion": "",
                "unique_answer_rationale": "",
            },
            "review": {"blind": {"status": "pending"}, "source": {"status": "pending"}},
        }],
        "workflow": {"phases": [], "revision_history": []},
    }


def section_counts(questions: list[dict]) -> Counter:
    return Counter(q["section"] for q in questions)


def render_paper(data: dict) -> str:
    quiz, questions = data["quiz"], data["questions"]
    counts = section_counts(questions)
    kinds = Counter(q["source"]["kind"] for q in questions)
    lines = [f"# {quiz['title']}", "", f"- 日期：{quiz['date']}",
             f"- 题数：{len(questions)} 题（形式选择 {counts['form']} ＋ 句子排序 {counts['order']} ＋ 篇章完形 {counts['cloze']}）。",
             f"- 日本語NET题源：{kinds['teaching_exercise']}道网站原题，{kinds['derived_from_example']}道AI根据网站例句改编题；非官方真题。",
             f"- 建议时间：{quiz.get('suggested_minutes', len(questions))}分钟。答案与来源另存，做完后再查阅。", ""]
    for section in SECTIONS:
        items = [q for q in questions if q["section"] == section]
        if not items:
            continue
        lines += [f"## {SECTION_LABELS[section]}（{items[0]['number']}–{items[-1]['number']}）", ""]
        if section == "order":
            lines += ["将四个语块排列成自然的句子，并提交完整语序。", ""]
        elif section == "cloze":
            lines += ["阅读短文，根据上下文选择最合适的一项。", ""]
        for q in items:
            prompt = str(q.get("paper_prompt") or q["prompt"])
            first, *rest = prompt.splitlines()
            lines.append(f"### {q['number']}. {first}")
            if rest:
                lines += [""] + rest
            lines.append("")
            for key in "1234":
                lines.append(f"{key}. {q['options'][key]}")
            lines.append("")
    lines += ["## 答案填写区", "", "```text"]
    for section, label in (("form", "第一部分"), ("order", "第二部分"), ("cloze", "第三部分")):
        nums = [q["number"] for q in questions if q["section"] == section]
        if nums:
            lines.append(f"{label}（{nums[0]}–{nums[-1]}）：")
            lines.append(", ".join(f"{n}-" for n in nums))
            lines.append("")
    lines += ["```", ""]
    return "\n".join(lines)


def render_answers(data: dict) -> str:
    lines = [f"# {data['quiz']['title']} · 答案解析", ""]
    current = None
    for q in data["questions"]:
        if q["section"] != current:
            current = q["section"]
            lines += [f"## {SECTION_LABELS[current]}", ""]
        correct = q["correct_option"]
        kind_label = "日本語NET网站原题" if q["source"]["kind"] == "teaching_exercise" else "AI根据日本語NET例句改编"
        lines += [f"### 第 {q['number']} 题（{q['id']}）", "",
                  f"**题目**：{q.get('answer_prompt') or q['prompt']}",
                  f"**翻译**：{q['translation']}",
                  f"**考点**：{'、'.join(q['tested_cards'])}",
                  f"**题源类型**：{kind_label}",
                  f"**来源**：{q['source']['title']}；{q['source']['url']}；{q['source']['locator']}"]
        if q["section"] == "order":
            lines.append(f"**推荐语序**：{q['recommended_order']}（{q.get('order_explanation', '见解析')}）")
        lines += [f"**正确项**：{correct}（{q['options'][correct]}）",
                  f"**正确接续**：{q['conjugation']}", "",
                  f"**解析**：{q['correct_explanation']}"]
        for key in "1234":
            lines.append(f"- 选项 {key}（{q['options'][key]}）：{q['option_explanations'][key]}")
        lines.append("")
    return "\n".join(lines)


def card_frontmatter(q: dict, level: str) -> dict:
    fields = ["id", "revision", "item_type", "prompt", "translation", "tested_cards", "conjugation",
              "options", "correct_option", "correct_explanation", "option_explanations", "source"]
    card = {key: q[key] for key in fields}
    card["level"] = level
    if q["section"] == "order":
        card["recommended_order"] = q["recommended_order"]
    return card


def render_card(q: dict, level: str) -> str:
    fm = json.dumps(card_frontmatter(q, level), ensure_ascii=False, indent=2)
    lines = ["---", fm, "---", "", q["prompt"], ""]
    for key in "1234":
        lines.append(f"{key}. {q['options'][key]}")
    return "\n".join(lines) + "\n"


def output_paths(base: Path, data: dict) -> dict[str, Path]:
    slug = data["quiz"]["slug"]
    return {
        "paper": base / "quizzes/papers" / f"{slug}.md",
        "answers": base / "quizzes/answers" / f"{slug}-answers.md",
        "manifest": base / "quizzes/sources" / slug / "manifest.json",
    }


def record_phase(data: dict, name: str, started: str, ended: str, duration: float, metrics=None) -> None:
    workflow = data.setdefault("workflow", {})
    workflow.setdefault("phases", []).append({
        "name": name, "started_at": started, "ended_at": ended,
        "duration_seconds": round(duration, 3), "metrics": metrics or {},
    })


def cmd_template(args) -> int:
    path = Path(args.output)
    if path.exists():
        raise ValueError(f"拒绝覆盖既有文件：{path}")
    atomic_json(path, template_data())
    print(path)
    return 0


def cmd_validate(args) -> int:
    data = read_json(Path(args.draft))
    errors = validate_data(data, Path(args.root).resolve(), args.stage)
    report = {"ok": not errors, "stage": args.stage, "questions": len(data.get("questions", [])), "errors": errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def cmd_render(args) -> int:
    started_at = now_iso()
    started = time.monotonic()
    draft_path = Path(args.draft)
    data = read_json(draft_path)
    repo_root = Path(args.root).resolve()
    stage = "final" if args.final else "preflight"
    errors = validate_data(data, repo_root, stage)
    if errors:
        raise ValueError("渲染前校验失败：\n- " + "\n- ".join(errors))
    base = repo_root / "jlpt-notes" if args.final else Path(args.preview_dir).resolve()
    paths = output_paths(base, data)
    card_paths = [base / "quizzes/questions" / f"{q['id']}.md" for q in data["questions"]]
    targets = [*paths.values(), *card_paths]
    existing = [str(p) for p in targets if p.exists()]
    if existing:
        raise ValueError("拒绝覆盖既有产物：\n- " + "\n- ".join(existing))
    atomic_text(paths["paper"], render_paper(data))
    atomic_text(paths["answers"], render_answers(data))
    for q, path in zip(data["questions"], card_paths):
        atomic_text(path, render_card(q, data["quiz"]["level"]))
    duration = time.monotonic() - started
    record_phase(data, "render", started_at, now_iso(), duration, {"mode": "final" if args.final else "preview", "files": len(targets)})
    atomic_json(paths["manifest"], data)
    atomic_json(draft_path, data)
    print(json.dumps({"paper": str(paths["paper"]), "answers": str(paths["answers"]),
                      "cards": [str(p) for p in card_paths], "manifest": str(paths["manifest"])},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_revise(args) -> int:
    path = Path(args.draft)
    data = read_json(path)
    target = next((q for q in data.get("questions", []) if q.get("id") == args.question_id), None)
    if target is None:
        raise ValueError(f"未找到题卡：{args.question_id}")
    revision = int(target.get("revision", 1)) + 1
    if revision > 3:
        raise ValueError("已达到最多两轮修订；应弃用该题")
    target["revision"] = revision
    target["preflight"] = {"status": "pending"}
    target["review"] = {"blind": {"status": "pending"}, "source": {"status": "pending"}}
    if target.get("source", {}).get("kind") == "derived_from_example":
        target["source"].setdefault("transformations", []).append(f"第{revision - 1}轮修订：{args.reason}")
    data.setdefault("workflow", {}).setdefault("revision_history", []).append({
        "question_id": args.question_id, "revision": revision,
        "reason": args.reason, "at": now_iso(),
    })
    atomic_json(path, data)
    print(json.dumps({"question_id": args.question_id, "revision": revision, "review_reset_only_for": args.question_id}, ensure_ascii=False))
    return 0


def parse_metrics(values: list[str]) -> dict:
    metrics = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError(f"metric 必须为 key=value：{raw}")
        key, value = raw.split("=", 1)
        if not key:
            raise ValueError("metric key 不能为空")
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                pass
        metrics[key] = value
    return metrics


def cmd_phase(args) -> int:
    if args.name not in PHASES:
        raise ValueError(f"未知阶段：{args.name}")
    path = Path(args.draft)
    data = read_json(path)
    workflow = data.setdefault("workflow", {})
    active = workflow.setdefault("active_phases", {})
    if args.action == "start":
        if args.name in active:
            raise ValueError(f"阶段已开始：{args.name}")
        active[args.name] = now_iso()
        result = {"name": args.name, "started_at": active[args.name]}
    else:
        started_at = active.pop(args.name, None)
        if not started_at:
            raise ValueError(f"阶段尚未开始：{args.name}")
        start_dt = datetime.fromisoformat(started_at)
        end_dt = datetime.now().astimezone()
        duration = (end_dt - start_dt).total_seconds()
        record_phase(data, args.name, started_at, end_dt.isoformat(timespec="seconds"), duration, parse_metrics(args.metric))
        result = data["workflow"]["phases"][-1]
    atomic_json(path, data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JLPT 结构化出卷流水线")
    sub = parser.add_subparsers(dest="command", required=True)
    template = sub.add_parser("template")
    template.add_argument("--output", required=True)
    template.set_defaults(func=cmd_template)
    validate = sub.add_parser("validate")
    validate.add_argument("--root", required=True, help="含 jlpt-notes 的仓库根")
    validate.add_argument("--draft", required=True)
    validate.add_argument("--stage", choices=("preflight", "final"), default="preflight")
    validate.set_defaults(func=cmd_validate)
    render = sub.add_parser("render")
    render.add_argument("--root", required=True, help="含 jlpt-notes 的仓库根")
    render.add_argument("--draft", required=True)
    mode = render.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview-dir")
    mode.add_argument("--final", action="store_true")
    render.set_defaults(func=cmd_render)
    revise = sub.add_parser("revise")
    revise.add_argument("--draft", required=True)
    revise.add_argument("--question-id", required=True)
    revise.add_argument("--reason", required=True)
    revise.set_defaults(func=cmd_revise)
    phase = sub.add_parser("phase")
    phase.add_argument("--draft", required=True)
    phase.add_argument("--name", required=True)
    phase.add_argument("--action", choices=("start", "end"), required=True)
    phase.add_argument("--metric", action="append", default=[])
    phase.set_defaults(func=cmd_phase)
    return parser


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
