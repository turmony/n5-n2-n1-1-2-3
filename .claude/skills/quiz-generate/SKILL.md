---
name: quiz-generate
description: 从本地 JLPT 语法卡片生成题库试卷。文法三题型（默认 34 题＝形式选择 20＋排序 7＋完形 7），错题驱动选卡，试卷/答案/题卡三件套一次生成并强制通过机械校验与盲测审题——题必带答案，答案与试卷永不脱节。当用户说"出题／出卷／出新卷／生成试卷／出 N4 卷"等时使用。
---

# JLPT 出题流程（quiz-generate）

参数（从用户话语解析，缺省走默认）：级别（默认 n4）、结构覆盖（如"排序 10"→ 20+10+7 之类，仅调整数量）、选卡指定（如"G30-60""のに专场"——给了就跳过选卡提议）。

## 第 0 步：读规则

先读仓库根 `AGENTS.md` 与 `docs/superpowers/specs/2026-08-20-quiz-skill-design.md` 第 4 节（如仍在）。数据格式基准：既有卷 `jlpt-notes/quizzes/papers/` 最新一卷与对应 answers、questions 是格式的唯一权威样例，生成前先看一份。

## 第 1 步：选卡提议（先提议、后动笔；用户已指定卡片则跳过）

1. 读 `jlpt-notes/quizzes/attempts.jsonl`：按题卡聚合错次与 error_tags；
2. 读最近的 `jlpt-notes/quizzes/results/*.md`：薄弱区结论（连败题型、修饰链等）；
3. 读 `jlpt-notes/grammar/<level>/*.md` 的 frontmatter：`next_review` 到期、`status=confirmed` 才可考；
4. 产出提议表：卡号｜考点｜出题侧重｜分配题型｜理由（错 X 次／连败 N 卷／到期），并给出建议文件名（序号在"级别＋系列"内接续）；
5. **停下等用户确认或修改**，确认后才继续。

## 第 2 步：生成三件套（一次写全，格式照抄最新一卷）

- 试卷 `papers/YYYY-MM-DD-<level>-<主题>-test-N.md`：盲答用，不含任何答案；含作答说明、建议时间、排序规则速览、尾部"答案填写区"代码块；
- 答案 `answers/<试卷名>-answers.md`：每题条目含 题目／翻译／考点（卡号）／正确项／正确接续（粗体空格成分）／解析＋三个干扰项逐项解析；排序题另含 **推荐语序**（4 位数字串＋块文字）且解析文字里逐块编号顺序必须与语序串一致；
- 题卡 `questions/<LEVEL>-Q-XXXX.md`：JSON frontmatter（id/revision/level/item_type/prompt/translation/tested_cards/conjugation/options/correct_option/correct_explanation/option_explanations；排序题再加 recommended_order），编号接续该级别既有最大号；
- 只出文法三题型；每题恰一个最佳答案；排序题必须仅有一种自然语序（块设计要锁死唯一解，吸取卷四 Q21/Q22 教训）。

## 第 3 步：机械校验（必须执行，不可跳过）

```
uv run .claude/skills/quiz-generate/scripts/validate_quiz.py --paper <试卷路径> --answers <答案路径> --structure <如 20,7,7>
```

- 有 [错误] → 修复（不改题意，只修机械问题）→ 重跑；最多 3 轮，仍有错误 → 停止并上报；
- [警告]（如相似度查重）→ 带入第 4 步让盲测员重点复核。

## 第 4 步：盲测审题（新上下文，防出题者自证）

用 Agent 工具派 general-purpose 子代理，prompt 按下方模板（把 <试卷全文> 与 <语法卡目录绝对路径> 填入；**不传答案文件、不传题卡路径**，并明确禁读 `jlpt-notes/quizzes/answers/` 与 `jlpt-notes/quizzes/questions/`——题卡含正确答案）：

> 你是独立审题员。下面是一份 JLPT 试卷与可自由查阅的语法卡目录 <语法卡目录路径>。禁止读取 quizzes/answers/ 与 quizzes/questions/ 下任何文件。
> 第一阶段：独立作答整卷（不查答案，可查语法卡）。排序题给出完整语序与排序理由。输出逐题：题号｜你的答案｜信心（高/中/低）。
> 第二阶段：我会给你标准答案，你只对与你不一致的题，重读对应考点卡后二次作答，输出：题号｜你的答案｜标准答案｜复核后立场（坚持己见/改判标准答案/认为题目有缺陷）｜理由。
> 现在开始第一阶段，只输出作答结果。

收到其第一阶段结果后，把标准答案（仅正确项列表）发给它做第二阶段。另把第 3 步的全部 [警告] 一并给它复核。

## 第 5 步：分歧裁决与定稿

把盲测分歧清单（题号｜双方答案｜盲测理由｜复核立场）呈现用户裁决。用户裁定后执行修正（改题/改答案/维持），**凡有改动必须重跑第 3 步校验**。卷四先例：双正确题计缺陷，须修题锁死唯一解或答案补注。

## 第 6 步：交付

- 汇报：三件套路径、校验结果摘要（几轮全绿）、盲测分歧与裁决记录；
- git 提交：`feat: 添加 <卷名>（主题，34 题，覆盖卡段，题卡 N4-Q-XXXX~XXXX，校验与盲测通过）`，风格照抄 git log 既有出题提交。

## 出题侧自检清单（历史坑，生成时逐条过）

1. 排序题：语序是 1–4 排列；★ 位数字＝正确项；解析块编号＝语序串；题卡与答案语序一致；
2. 题卡编号接续最大号且连续，不覆盖既有卡；
3. 新题干不与既有题重复（校验器 C6 兜底，出题时主动避开近似句）；
4. 每题四项解析齐全（正确项＋三个干扰项）；
5. 排序题块设计锁死唯一自然语序；
6. 完形题卡 prompt 须含整段文章与（NN）空格标记。

## 进化循环

交付后若用户指出新漏错：说「把这次的坑加进 skill」→ 本清单加条目 ＋ validate_quiz.py 加断言 ＋ test_regression_incidents.py 加变异测试 → `uv run --with pytest pytest .claude/skills/quiz-generate/scripts/tests -v` 全绿才算完成。
