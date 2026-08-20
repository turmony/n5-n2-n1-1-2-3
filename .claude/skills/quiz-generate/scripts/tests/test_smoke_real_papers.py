"""对真实 N4 覆盖卷 1–6 整卷跑校验器。
预期：全部报错逐条归因——解析器 bug 修复或白名单登记，无未归因报错；
卷五/卷六各含 7 条良性翻译漂移白名单条目。
卷四 Q1/Q21/Q22 为语义缺陷（双正确/双自然语序/参考语序不成立），机械层
不应也无法报出，属盲测层验收样例（见 SKILL.md 盲测协议）。
"""
import json
from pathlib import Path

import pytest

from validate_quiz import run_validation

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = next(p for p in TESTS_DIR.parents if (p / "jlpt-notes").is_dir())
QUIZES = REPO_ROOT / "jlpt-notes/quizzes"
KNOWN = json.loads((TESTS_DIR / "fixtures/known-real-findings.json").read_text(encoding="utf-8"))

# 真实卷存于 quizzes/papers/（brief 原文 glob 少了 papers/ 一层，按仓库实际布局修正）
PAPERS = sorted(QUIZES.glob("papers/2026-*-n4-coverage-test-*.md"))
assert PAPERS, "未找到 N4 覆盖卷"

# 语法卡 N4-G-0001～0120 在主检出中尚未入库（untracked），git worktree 里不存在；
# 缺卡时 C4 会全量误报。跑 smoke 前须从主检出只读同步到本 worktree（不入库），
# 详见 fixtures/known-real-findings.md 的运行前提一节
assert any((REPO_ROOT / "jlpt-notes/grammar/n4").glob("N*-G-*.md")), (
    "jlpt-notes/grammar/n4/ 下没有语法卡：请先从主检出复制 N4-G-*.md 到本 worktree"
    "（只读同步，不提交），否则 C4 检查将全量误报")


@pytest.mark.parametrize("paper", PAPERS, ids=lambda p: p.stem)
def test_real_paper_no_unexpected_errors(paper):
    answers = QUIZES / "answers" / (paper.stem + "-answers.md")
    findings = run_validation(paper, answers, REPO_ROOT, (20, 7, 7))
    errors = [f for f in findings if f.severity == "error"]
    known = KNOWN.get(paper.stem, [])
    unexpected = []
    for f in errors:
        if not any(all(kw in f.message for kw in k["message_contains"]) and f.check == k["check"]
                   for k in known):
            unexpected.append(f)
    assert not unexpected, "\n".join(f"[{f.check}] {f.location}: {f.message}" for f in unexpected)
