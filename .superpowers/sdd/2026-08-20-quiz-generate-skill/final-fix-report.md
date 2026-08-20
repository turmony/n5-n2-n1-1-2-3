# 终审修复报告（final whole-branch review fix wave）

- 日期：2026-08-21
- 基线：dd5af1b（终审 review-987d842..dd5af1b.diff 的 5 项 findings）
- 范围：仅 docs/superpowers/specs、.claude/skills/{quiz-generate,quiz-grade}、本报告；未触碰 jlpt-notes/ 与 known-real-findings 白名单内容

## 逐项处置

### Important 1 — spec 验收②措辞与白名单事实矛盾 → fixed

- `docs/superpowers/specs/2026-08-20-quiz-skill-design.md` 验收标准②：原括号段「（卷五/卷六零错误；卷一～卷四的报错逐条归因——真实机械缺陷登记 known-real-findings）」按 Task 7 裁定替换为「全部报错逐条归因（解析器修复或白名单登记），无未归因报错，不对具体卷承诺零错误」（以破折号接入句首的「解析器零误报」之后）；卷四 Q1/Q21/Q22 盲测层验收样例句保留。
- `scripts/tests/test_smoke_real_papers.py` 模块 docstring 同步改为「预期：全部报错逐条归因——解析器 bug 修复或白名单登记，无未归因报错；卷五/卷六各含 7 条良性翻译漂移白名单条目」。

### Important 2 — quiz-grade SKILL.md 第 4 步补 item_type 历史说明 → fixed

- `.claude/skills/quiz-grade/SKILL.md` 第 4 步 JSON 样例代码块之后新增一段：「item_type 一律取题卡 frontmatter 的值；历史 attempts.jsonl 行存在 grammar_form 旧值（与题卡 text_grammar 不一致），属已知历史不一致——勿模仿也勿改写旧行。」

### Minor 3 — 删死变量 → fixed

- `quizlib/parsing.py` `parse_paper`：删除 `seen_option_lines_after_header` 三处（初始化/题头重置/选项置位），该变量只写不读；H2 边界终结选项归集的行为（`current = None`）不受影响，`test_parse_paper_h2_interlude_stops_option_ingestion` 仍绿。

### Minor 4 — C1 重复消息带上冲突文件路径 → fixed

- `quizlib/parsing.py` `load_question_cards`：`__duplicates__` 值由 `list[str]`（id 列表）改为 `list[(cid, [涉事文件名…])]`——装载时按 `files_by_id` 收集每个 id 的全部文件名，仅 len>1 者登记；docstring 同步更新。
- `quizlib/checks.py` C1 消息改为「题卡 id 重复：N4-Q-0002（N4-Q-0002.md、N4-Q-0004.md）」式（含「重复」关键词，既有测试依赖不变）；`check_duplicates` 只按 key 跳过 `__duplicates__`，不受值结构影响。
- `test_checks.py::test_c1_duplicate_id` 追加断言：消息同时含 `N4-Q-0002.md` 与 `N4-Q-0004.md`。

### Minor 5 — star_pos 越界防护 → fixed

- `quizlib/checks.py` `check_order_invariants`：`order[q.star_pos - 1]` 前加 `elif not 1 <= q.star_pos <= 4` 防护，报 `C2`「★ 位（第{q.star_pos}空）超出 1–4」并跳过，不再抛 IndexError。
- `test_checks.py` 新增 `test_c2_star_position_out_of_range`：排序题干改为 5 空位（＿＿ ＿＿ ＿＿ ＿＿ ★），断言报含「超出」「5」的 C2 Finding。

## 覆盖测试

命令（worktree 根目录）：

```
uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v
```

输出摘要：**60 passed in 5.39s**（原 59 ＋ 新增 `test_c2_star_position_out_of_range`；`test_c1_duplicate_id` 为原位增强断言），无失败无跳过；含六套真实卷 smoke（test-real-papers 1–6 全绿，白名单匹配不受 C1 消息改写影响——白名单内无 C1 条目）。

## 提交

- `fix:` — parsing/checks/test_checks/test_smoke_real_papers/quiz-grade SKILL.md（代码＋测试＋skill 说明）
- `docs:` — spec 验收措辞＋本报告
