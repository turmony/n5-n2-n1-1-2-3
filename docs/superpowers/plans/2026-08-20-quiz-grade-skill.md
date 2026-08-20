# quiz-grade 判分 Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `.claude/skills/quiz-grade/`：固化「读答案填写区→判分→五段式成绩报告→attempts.jsonl 记录→薄弱区结论→提交」流程的判分 skill，报告格式与现有 N4 成绩报告完全一致且全部题目含解析。

**Architecture:** 单 SKILL.md ＋ 一个报告模板参照文件（从真实卷六报告提取骨架）。无代码，无测试框架——验收靠模板比对与一次真实判分走查。

**Tech Stack:** 纯 Markdown（SKILL.md 指令 + references/result-template.md）。

**Spec:** `docs/superpowers/specs/2026-08-20-quiz-skill-design.md` §5

## Global Constraints

- 不改动 `jlpt-notes/` 既有内容（判分产物 results/attempts 属新增与追加，允许）；
- `attempts.jsonl` 只追加，不重写既有行；
- 提交信息沿用仓库风格（`feat: 记录 …`）；
- skill 目录名＝命令名＝`quiz-grade`；描述含中文触发词（判分/成绩/作答完了）；
- 报告五段式顺序不可变；全部题目（对的错的）都必须有解析。

## 数据格式基准（摘自真实卷六）

- 作答输入：试卷尾部 `## 答案填写区` 代码块，形如 `1-, 2-, …`（学习者把答案填在 `-` 后）；排序题为完整语序（如 `21：1324`）；可带 `?` 表不确定。
- attempts.jsonl 行 schema：`{"question_id","revision","item_type","selected_option","is_correct","uncertain","error_tags":[],"date":"YYYY-MM-DD"}`。
- results 文件名：`<试卷 stem>-result.md`。

---

### Task 1: 报告模板参照文件

**Files:**
- Create: `.claude/skills/quiz-grade/references/result-template.md`

**Interfaces:**
- Produces: 五段式模板（Task 2 的 SKILL.md 与未来所有判分调用都按此产出报告）。

- [ ] **Step 1: 写模板（全文如下，骨架取自 2026-08-20-n4-coverage-test-6-result.md，占位符用 <＞ 标记）**

```markdown
# <YYYY-MM-DD> <N4 覆盖卷N（主题）>：作答报告

- 判卷说明：<答案来源与核对方式，如"学习者将答案直接写在试卷「答案填写区」，逐题核对，映射无歧义">
- 计分标准：排序题按完整句是否自然、语法成立计分
- <待确认事项（如有）：逐条说明第 N 题的疑点、处理口径、经确认后成绩如何变化>
- <出题侧更正记录（如有）：日期＋哪些题的什么错误已同步修正>
- 本报告解析**全部 <34> 题**，每题含：题目、翻译、考点卡、你的答案、卡片接续规则、**意思（接续规则下方）**、解析（对题给要点，错题给完整诊断）

## 成绩概览

- 第一部分（形式选择）：<16>／<20>（<80.0%>）
- 第二部分（句子排序）：<6>／<7>（<85.7%>，<跨卷曲线对比，如"六卷最高，曲线 6→5→4→4→5→6">）
- 第三部分（篇章完形）：<4>／<7>（<57.1%>）
- 全卷得分：<26>／<34>（<76.5%>）
- <级别>卷曲线：<逐卷得分列表>（<阶段总结>）
- 错题：<题号列表>
- 不确定（?）：<题号列表或"无">

## 全部考点清单（<34> 题，对错全列）

| 题 | 考点卡 | 考点 | 结果 |
|---|---|---|---|
| <1> | <N4-G-0008> | <なので（な形接续）> | <✓> |
| <21> | <N4-G-0011> | <排序：の连锁＋たことが> | <✗（待确认）> |

---

## 逐题全解析

### 第一部分（1–20）形式选择

#### 第 <1> 题 <✓/✗（待确认）>（<N4-Q-0282>）｜<考点短名>

**题目**：<题干原文>
**翻译**：<中文翻译>
**你的答案**：<选项号（选项文字）>＝正确 ／ ≠正确（正确：<N>（<文字>））
**接续规则**（<N4-G-0008>）：<接续公式（粗体空格成分）>
**意思**：<句型含义>
**解析**：<对题：作答要点回顾；错题：完整诊断——错在哪、正确形式、正确骨架加粗>

<错题额外段落（视需要）>
- **错在哪**：<错误选项为什么错>
- **正确形式**：<整句正确形态>

### 第二部分（21–27）句子排序

#### 第 <21> 题 <✓/✗>（<N4-Q-0302>）｜<考点短名>

**题目**：<见试卷第 N 题框架 或 题干＋块列表>
**翻译**：<中文翻译>
**你的语序**：<提交的语序串>（拼句：<拼出的句子>）
**推荐语序**：<3142>（<块顺序文字>）
**接续规则**（<N4-G-0011>）：<接续公式>
**意思**：<句型含义>
**解析**：<排序理由：块间修饰关系、贴动词/贴框架规则；学习者语序为何成立或不成立；★处是哪块>

### 第三部分（28–34）篇章完形

#### 第 <28> 题 <✓/✗>（<N4-Q-0309>）｜<考点短名>

**题目**：<含（NN）空格的原文句>
**翻译**：<中文翻译>
**你的答案**：<选项号（文字）>＝正确 ／ ≠正确
**接续规则**（<N4-G-0015>）：<接续公式>
**意思**：<句型含义>
**解析**：<上下文逻辑＋句型判断；错题给完整诊断>

---

## 薄弱区结论（下次出题的直接输入）

### 仍薄弱
- <题型/卡片：连败卷数与具体错型>

### 已攻克
- <本卷全对的既往薄弱项>

### <出题侧修订建议（如有）>
<待确认缺陷题的修题方向>
```

- [ ] **Step 2: 人工核验**

- 与真实卷六报告（`jlpt-notes/quizzes/results/2026-08-20-n4-coverage-test-6-result.md`）逐段比对：五段顺序、成绩概览字段、考点清单表列、逐题六要素（题目/翻译/你的答案/接续规则/意思/解析）一致；
- Run: `ls ".claude/skills/quiz-grade/references/result-template.md"`（存在性检查）

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/quiz-grade/references/result-template.md
git commit -m "feat: 判分报告五段式模板（提取自覆盖卷六真实报告，全部题目含六要素解析）"
```

---

### Task 2: quiz-grade SKILL.md（流程指令全文）

**Files:**
- Create: `.claude/skills/quiz-grade/SKILL.md`

**Interfaces:**
- Consumes: `references/result-template.md`（Task 1）、答案文件（quiz-generate 产物）、试卷答案填写区、attempts.jsonl schema。

- [ ] **Step 1: 写 SKILL.md（全文如下）**

````markdown
---
name: quiz-grade
description: 判定学习者的 JLPT 试卷作答并生成成绩报告。读取试卷答案填写区，对照答案文件逐题判定（排序题按完整句是否自然计分），产出五段式报告（成绩概览＋跨卷曲线＋全部考点清单＋全部题目逐题全解析＋薄弱区结论），追加 attempts.jsonl，薄弱区结论直接作为下次出题依据。当用户说"判分／判卷／成绩／作答完了／对答案"等时使用。
---

# JLPT 判分流程（quiz-grade）

## 第 0 步：读规则与格式权威样例

先读仓库根 `AGENTS.md`；报告格式唯一权威＝本 skill 的 `references/result-template.md` ＋ 最近一份真实报告 `jlpt-notes/quizzes/results/` 最新文件。

## 第 1 步：读作答与答案

1. 从试卷尾部 `## 答案填写区` 代码块逐题读取学习者作答（`N-答案`）；排序题为完整语序串；`?` 或答案后带?＝不确定；
2. 读对应 `jlpt-notes/quizzes/answers/<卷名>-answers.md` 逐题正确项（这是唯一答案来源，与题卡同源、已经 quiz-generate 质检）；
3. 映射有歧义（空着、看不清、题号对不上）→ 先向用户确认，不得猜。

## 第 2 步：判分规则

- 形式选择/完形：选项号精确比对；
- 排序题：**按完整句是否自然、语法成立计分**——学习者语序≠推荐语序时，先拼出其完整句判断是否自然成立；成立即 ✓（并标注"存在多自然语序，属题目缺陷，待确认修题"），不成立才 ✗；
- 疑似笔误（如提交语序与正确语序仅一处相邻互换、无法拼句）：标「待确认」，按卷三第 23 题先例暂计 ✗ 并注明"经确认后更正"；
- 每题判定都要能从答案文件的解析里找到依据；发现答案文件本身有误 → 停下报告用户，不得静默改判。

## 第 3 步：成绩报告

按 `references/result-template.md` 产出 `jlpt-notes/quizzes/results/<试卷 stem>-result.md`，五段不可缺、顺序不可变：

1. 头部说明（判卷说明/计分标准/待确认事项/出题侧更正记录）；
2. 成绩概览（三部分分项、全卷得分、**跨卷曲线**——自动读同级别历史 results 的全卷得分列成曲线并给阶段总结、错题清单、不确定清单）；
3. 全部考点清单表（每题一行：题号/考点卡/考点/✓✗，全列）；
4. **逐题全解析（全部题目，一题不落）**：六要素——题目、翻译、你的答案、接续规则（含卡号）、意思、解析；对题给要点、错题给完整诊断（错在哪＋正确形式）；
5. 薄弱区结论：仍薄弱（连败卷数＋错型）/已攻克/出题侧修订建议——这段是下次 quiz-generate 选卡提议的直接输入，写具体到卡号。

## 第 4 步：attempts.jsonl 追加

对每题追加一行（只追加，不重写文件既有内容）：

```json
{"question_id": "<N4-Q-XXXX>", "revision": <题卡 revision>, "item_type": "<text_grammar|sentence_composition>", "selected_option": "<选项号或语序串>", "is_correct": <true|false>, "uncertain": <true|false>, "error_tags": ["<从错因提炼的短标签>"], "date": "<YYYY-MM-DD>"}
```

答对与不确定但答对：error_tags 为 `[]`；答错：从解析提炼 1–3 个短标签（如「形容词过去否定」「接续错误」「修饰链断裂」）。

## 第 5 步：提交

git 提交：`feat: 记录 <卷名>作答成绩（<得分>，<一句话亮点与薄弱区>，<待确认事项>，全<34>题逐题解析）`——风格照抄 git log 既有判分提交。

## 判分自检清单

1. 报告五段齐全、逐题全解析覆盖试卷全部题号（数一遍）；
2. 排序题每题都写了"拼句"再判定，未做数字串硬比对；
3. 跨卷曲线数字与历史 results 一致（抄错曲线＝事实错误）；
4. attempts.jsonl 行数＝试卷题数，schema 字段齐全；
5. 薄弱区结论具体到卡号与错型，可直接喂给出题提议。
````

- [ ] **Step 2: 人工核验**

- frontmatter 合法、name=目录名、描述含「判分/成绩」触发词；
- 与 Task 1 模板逐段对照（五段、六要素、跨卷曲线、attempts schema）无矛盾；
- Run: `git log --oneline -5`（确认既有判分提交风格，SKILL.md 第 5 步的提交模板与之相符）

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/quiz-grade/SKILL.md
git commit -m "feat: quiz-grade 判分 skill（答案填写区读取、完整句自然判分、五段式报告、attempts 追加、薄弱区反馈闭环）"
```

---

## Self-Review 记录（写计划时已执行）

- **Spec 覆盖**：spec §5 五步（读作答/判分/报告/记录/提交）→ Task 2 第 1–5 步；报告五段式与"全部题目解析"→ Task 1 模板＋Task 2 第 3 步；反馈闭环→模板"薄弱区结论"段＋SKILL 第 3 步第 5 段；无效排列先例→Task 2 第 2 步。无遗漏。
- **占位符**：模板中 `<＞` 为报告产出时的占位符（这是模板文件的本意），非计划占位符；任务步骤无 TBD。
- **类型一致**：文件名 `<试卷 stem>-result.md`、attempts 字段名与既有 jsonl 样例逐一核对一致（question_id/revision/item_type/selected_option/is_correct/uncertain/error_tags/date）。
