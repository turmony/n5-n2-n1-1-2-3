"""JLPT 试卷机械校验器。用法：
uv run .claude/skills/quiz-generate/scripts/validate_quiz.py \
  --paper jlpt-notes/quizzes/papers/X.md --answers jlpt-notes/quizzes/answers/X-answers.md
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quizlib.checks import (check_answer_completeness, check_card_ids,
                            check_consistency, check_duplicates,
                            check_grammar_refs, check_order_invariants,
                            check_structure)
from quizlib.models import ERROR, Finding
from quizlib.parsing import (load_grammar_ids, load_question_cards,
                             parse_answers, parse_paper)

CHECK_ORDER = ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]

# Windows 管道/重定向下 stdout 默认用本地代码页（如 cp936），会破坏 --json 的
# UTF-8 契约与人读报告里的假名；统一强制 UTF-8 输出
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def find_root(start: Path) -> Path:
    p = start.resolve()
    while p != p.parent:
        if (p / "jlpt-notes").is_dir():
            return p
        p = p.parent
    raise SystemExit(f"未找到含 jlpt-notes 的仓库根（从 {start} 向上）")


def infer_level(answers: list) -> str:
    levels = [e.card_id.split("-")[0] for e in answers if "-" in e.card_id]
    return max(set(levels), key=levels.count) if levels else "N4"


def run_validation(paper_path: Path, answers_path: Path, root: Path,
                   expected_counts=(20, 7, 7), level: str | None = None):
    paper = parse_paper(paper_path.read_text(encoding="utf-8"))
    answers = parse_answers(answers_path.read_text(encoding="utf-8"))
    cards = load_question_cards(root / "jlpt-notes/quizzes")
    grammar_ids = load_grammar_ids(root / "jlpt-notes")
    level = level or infer_level(answers)
    findings: list[Finding] = []
    findings += check_structure(paper, expected_counts)
    findings += check_answer_completeness(paper, answers)
    findings += check_card_ids(answers, cards, level,
                               quizzes_dir=root / "jlpt-notes/quizzes")
    findings += check_order_invariants(paper, answers, cards)
    findings += check_consistency(paper, answers, cards)
    findings += check_grammar_refs(answers, grammar_ids, level)
    findings += check_duplicates(answers, cards)
    findings.sort(key=lambda f: (CHECK_ORDER.index(f.check), f.location))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="JLPT 试卷机械校验器")
    ap.add_argument("--paper", required=True)
    ap.add_argument("--answers", required=True)
    ap.add_argument("--root", default=None, help="含 jlpt-notes 的仓库根，默认从 --paper 向上找")
    ap.add_argument("--structure", default="20,7,7", help="形式选择,排序,完形 题数")
    ap.add_argument("--level", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    paper_path, answers_path = Path(args.paper), Path(args.answers)
    root = Path(args.root) if args.root else find_root(paper_path)
    expected = tuple(int(x) for x in args.structure.split(","))

    findings = run_validation(paper_path, answers_path, root, expected, args.level)
    errors = [f for f in findings if f.severity == ERROR]
    warns = [f for f in findings if f.severity != ERROR]

    if args.json:
        print(json.dumps({
            "ok": not errors,
            "paper": str(paper_path),
            "error_count": len(errors),
            "warn_count": len(warns),
            "findings": [f.__dict__ for f in findings],
        }, ensure_ascii=False, indent=2))
    else:
        for f in errors:
            print(f"[{f.check}][错误] {f.location}：{f.message}")
        for f in warns:
            print(f"[{f.check}][警告] {f.location}：{f.message}")
        print(f"校验完成：{len(errors)} 错误 / {len(warns)} 警告")
        if not errors:
            print("机械校验通过")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
