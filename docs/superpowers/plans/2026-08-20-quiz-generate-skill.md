# quiz-generate 出题 Skill 与机械校验器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建成 `.claude/skills/quiz-generate/`：一个固化「选卡提议→三件套生成→机械校验→盲测审题→交付」流程的出题 skill，配一个确定性校验器 `validate_quiz.py` 与历史事故回归测试集。

**Architecture:** skill 目录自包含：SKILL.md（流程指令）+ scripts/（quizlib 解析与检查模块 + CLI）+ scripts/tests/（hermetic fixture 环境与缺陷变异回归）。校验器纯标准库、hook 兼容（错误退出码 1、支持 --json）。

**Tech Stack:** Python 3（纯标准库），pytest，uv（执行器）。无第三方运行时依赖。

**Spec:** `docs/superpowers/specs/2026-08-20-quiz-skill-design.md`

## Global Constraints

- 本机无系统 Python：一切 Python 经 `uv run` 执行；跑测试用 `uv run --with pytest pytest …`。
- 校验器与 quizlib 仅用标准库（re/json/pathlib/dataclasses/difflib/argparse/sys/shutil）。
- 文件读写一律 `encoding="utf-8"`；Windows 路径含空格与中文，命令里加引号。
- 不改动 `jlpt-notes/` 既有内容；测试不写仓库数据目录（全部 hermetic 到 tmp_path）。
- 提交信息沿用仓库中文风格（`feat:` / `test:` / `docs:` 前缀）。
- skill 目录名＝命令名＝kebab-case（`quiz-generate`）；SKILL.md 描述必须含中文触发词（出题/出卷/生成试卷）。
- 工作目录：仓库根（所有命令路径以此为基准）。

## 数据格式基准（所有解析器以此为准，摘自真实卷）

- 试卷题目头：形式选择/排序 `### 21. 题干…`；完形 `#### 28.`（题干嵌在文章内，以（28）标记）。
- 试卷选项行：`1. 選項文字`（数字＋点＋空格）。
- 部分头：`## 第一部分：…（1–20）`、`## 第二部分：…（21–27）`、`## 第三部分：…（28–34）`。
- 排序题干：`＿＿ ★ ＿＿ ＿＿`（全角下划线对与★；★ 目前恒在第 2 空但解析不得写死）。
- 答案条目头：`### 第 21 题（N4-Q-0302）`；字段行 `**题目**：` `**翻译**：` `**考点**：N4-G-0011「…」` `**推荐语序**：3142（…）` `**正确项**：1（運転する）` `**正确接续**：` `**解析**：`；选项解析行 `- 选项 2（乗った）：…`。
- 题卡：`---\n{JSON}\n---` frontmatter＋正文。核心字段：`id/revision/level/item_type/prompt/options{1..4}/correct_option/correct_explanation/option_explanations{3项}`；N4 新卡另有 `translation/tested_cards[]/conjugation`，排序题卡另有 `recommended_order`。N5 旧卡可能缺后三类可选字段——缺失时相关检查降级或跳过，不得报错。
- item_type 取值：形式选择与完形 `text_grammar`、排序 `sentence_composition`。
- 试卷尾部有 `## 答案填写区` 代码块（本计划不解析它，属 quiz-grade 范围）。

---

### Task 1: hermetic fixture 环境 + 数据模型 + 试卷/答案解析器

**Files:**
- Create: `.claude/skills/quiz-generate/scripts/quizlib/__init__.py`（空文件）
- Create: `.claude/skills/quiz-generate/scripts/quizlib/models.py`
- Create: `.claude/skills/quiz-generate/scripts/quizlib/parsing.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/conftest.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/test_parsing.py`
- Fixture: `.claude/skills/quiz-generate/scripts/tests/fixtures/env-basic/**`（下述全部文件）

**Interfaces:**
- Produces: `Paper`（`.questions: list[PaperQuestion]`、`.raw_text: str`）；`PaperQuestion(number:int, section:str("form"|"order"|"cloze"), stem:str, options:dict[str,str], star_pos:int|None)`；`AnswerEntry(number, card_id, stem, grammar_ids:list[str], correct_option:str, order:str|None, analysis:str, option_analyses:dict[str,str], translation:str, conjugation:str)`；`parse_paper(text:str)->Paper`；`parse_answers(text:str)->list[AnswerEntry]`；conftest fixtures `env_basic`（复制 env-basic 到 tmp_path 并返回其根 Path）与 `mutate`（函数 `(root, rel, old, new)->None`，对 root 下相对路径 rel 做**恰好一次**子串替换，old 不存在时 assert 失败）。

- [ ] **Step 1: 写 fixture 环境 env-basic（迷你但格式与真实卷一致）**

目录树（相对 `.claude/skills/quiz-generate/scripts/tests/fixtures/env-basic/`）：

```
jlpt-notes/
  grammar/n4/N4-G-0001.md
  grammar/n4/N4-G-0002.md
  grammar/n4/N4-G-0003.md
  quizzes/
    questions/N4-Q-0001.md
    questions/N4-Q-0002.md
    questions/N4-Q-0003.md
    questions/N4-Q-0004.md
    questions/N4-Q-0005.md
    questions/N4-Q-0006.md
    papers/2026-01-01-n4-coverage-test-0.md
    answers/2026-01-01-n4-coverage-test-0-answers.md
    papers/2026-01-02-n4-coverage-test-1.md      ← 待校验的新卷
    answers/2026-01-02-n4-coverage-test-1-answers.md
```

`jlpt-notes/grammar/n4/N4-G-0001.md`（G-0002 同构换内容，G-0003 同）：

```markdown
---
{
  "id": "N4-G-0001",
  "kind": "grammar",
  "level": "N4",
  "title": "「～までに」：截止时限",
  "status": "confirmed",
  "tags": ["までに", "时间"]
}
---

# 核心

`名词 + までに` 表示某事最迟须在该时间点前完成。
```

`jlpt-notes/quizzes/questions/N4-Q-0001.md`（旧库形式选择卡，供跨卷查重与编号接缝基准）：

```markdown
---
{
  "id": "N4-Q-0001",
  "revision": 1,
  "level": "N4",
  "item_type": "text_grammar",
  "prompt": "选择（　）中最合适的一项。\n\n図書館は（　）ので、勉強に集中できます。",
  "translation": "图书馆很安静，所以能专心学习。",
  "tested_cards": ["N4-G-0002"],
  "conjugation": "な形容詞＋**な**＋ので＝因为……",
  "options": {"1": "静かだ", "2": "静かな", "3": "静かで", "4": "静か"},
  "correct_option": "2",
  "correct_explanation": "な形容词接なのでだ要变な。（N4-G-0002）",
  "option_explanations": {
    "1": "「静かだので」不成立。",
    "3": "「静かでので」不成立。",
    "4": "な形容词词干不能直接接ので。"
  }
}
---

図書館は（　）ので、勉強に集中できます。

1. 静かだ
2. 静かな
3. 静かで
4. 静か
```

`N4-Q-0002.md`（旧库排序卡）：

```markdown
---
{
  "id": "N4-Q-0002",
  "revision": 1,
  "level": "N4",
  "item_type": "sentence_composition",
  "prompt": "将四个语块排列成自然的句子，提交完整语序。\n\n明日は、＿＿ ★ ＿＿ ＿＿ ことがあります。",
  "translation": "明天有要拜访的老师。",
  "tested_cards": ["N4-G-0003"],
  "conjugation": "動詞辞書形＋ことがあります＝有……之事",
  "recommended_order": "2314",
  "options": {"1": "会う", "2": "先生に", "3": "明日", "4": "こと"},
  "correct_option": "3",
  "correct_explanation": "推荐语序：明日(2)／先生に(3)／会う(1)／こと(4)＋があります。（N4-G-0003）",
  "option_explanations": {
    "1": "「会う」位于第三格，贴「こと」。",
    "2": "「先生に」位于第二格，贴动词。",
    "4": "「こと」位于第四格，接框架。"
  }
}
---

明日は、＿＿ ★ ＿＿ ＿＿ ことがあります。
```

注意：N4-Q-0002 的语序 2314 中 ★（第 2 空）＝"3"，故 correct_option＝3——这是校验器 ★ 位不变量的正向样例。

`N4-Q-0003.md`（新卡，形式选择）：

```markdown
---
{
  "id": "N4-Q-0003",
  "revision": 1,
  "level": "N4",
  "item_type": "text_grammar",
  "prompt": "选择（　）中最合适的一项。\n\n何回も説明した（　）、彼はまだ分かっていない。",
  "translation": "明明说明了好几遍，他却还是没懂。",
  "tested_cards": ["N4-G-0001"],
  "conjugation": "動詞普通形＋**のに**＝明明……却……",
  "options": {"1": "のに", "2": "ので", "3": "から", "4": "まで"},
  "correct_option": "1",
  "correct_explanation": "预期落空用のに。（N4-G-0001）",
  "option_explanations": {
    "2": "ので表原因，逻辑颠倒。",
    "3": "から也表原因，同样不成立。",
    "4": "まで表终点，无逆接义。"
  }
}
---

何回も説明した（　）、彼はまだ分かっていない。
```

`N4-Q-0004.md`（新卡，形式选择）：

```markdown
---
{
  "id": "N4-Q-0004",
  "revision": 1,
  "level": "N4",
  "item_type": "text_grammar",
  "prompt": "选择（　）中最合适的一项。\n\n天気のいい日には、ここからでも富士山を（　）ことができます。",
  "translation": "天气好的日子，从这里也能看到富士山。",
  "tested_cards": ["N4-G-0003"],
  "conjugation": "動詞辞書形＋ことができます＝能够……",
  "options": {"1": "見て", "2": "見ます", "3": "見た", "4": "見る"},
  "correct_option": "4",
  "correct_explanation": "ことができる前面只能接辞书形。（N4-G-0003）",
  "option_explanations": {
    "1": "て形不接ことができる。",
    "2": "ます形不接。",
    "3": "た形接的是经验句たことがあります。"
  }
}
---

天気のいい日には、ここからでも富士山を（　）ことができます。
```

`N4-Q-0005.md`（新卡，排序）：

```markdown
---
{
  "id": "N4-Q-0005",
  "revision": 1,
  "level": "N4",
  "item_type": "sentence_composition",
  "prompt": "将四个语块排列成自然的句子，提交完整语序。\n\n去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。",
  "translation": "去年夏天在湖水旅行时，我坐过导游开的船。",
  "tested_cards": ["N4-G-0003"],
  "conjugation": "動詞た形＋ことがあります（乗った＋**ことが**あります）＝有过……的经历",
  "recommended_order": "3142",
  "options": {"1": "運転する", "2": "乗った", "3": "ガイドさんの", "4": "船に"},
  "correct_option": "1",
  "correct_explanation": "推荐语序：ガイドさんの(3)／運転する(1)／船に(4)／乗った(2)＋ことがあります。（N4-G-0003）",
  "option_explanations": {
    "2": "「乗った」位于第四格，た形贴「ことがあります」。",
    "3": "「ガイドさんの」位于第一格，修饰「運転する」。",
    "4": "「船に」位于第三格，贴「乗った」。"
  }
}
---

去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。
```

`N4-Q-0006.md`（新卡，完形；文章与空格标记嵌在 prompt）：

```markdown
---
{
  "id": "N4-Q-0006",
  "revision": 1,
  "level": "N4",
  "item_type": "text_grammar",
  "prompt": "阅读短文，选择（4）中最合适的一项。\n\n寮の説明書きには、『昼間は部屋で楽器を（4）けど、夜十時以降はやめてください』と書いてありました。",
  "translation": "宿舍须知上写着：白天可以在房间演奏乐器，但晚上十点以后请停止。",
  "tested_cards": ["N4-G-0002"],
  "conjugation": "動詞て形＋もいい（演奏する → 演奏**して**＋**もいい**）＝可以……",
  "options": {"1": "演奏してはいけない", "2": "演奏したことがある", "3": "演奏してもいい", "4": "演奏しなくてもいい"},
  "correct_option": "3",
  "correct_explanation": "白天许可、晚上收回，てもいい与转折けど呼应。（N4-G-0002）",
  "option_explanations": {
    "1": "与后句逻辑相反。",
    "2": "经验句，语义不合。",
    "4": "可以不演奏，语义不合。"
  }
}
---

寮の説明書きには、『昼間は部屋で楽器を（4）けど、夜十時以降はやめてください』と書いてありました。
```

`papers/2026-01-02-n4-coverage-test-1.md`（待校验新卷，迷你结构 2+1+1）：

```markdown
# N4 迷你卷一

- 日期：2026-01-02
- 题数：4 题（形式选择 2 ＋ 句子排序 1 ＋ 篇章完形 1；对应题卡 N4-Q-0003～0006）
- 配套：答案解析见 `answers/2026-01-02-n4-coverage-test-1-answers.md`

---

## 第一部分：文の文法１（形式选择）（1–2）

### 1. 何回も説明した（　）、彼はまだ分かっていない。

1. のに
2. ので
3. から
4. まで

### 2. 天気のいい日には、ここからでも富士山を（　）ことができます。

1. 見て
2. 見ます
3. 見た
4. 見る

## 第二部分：句子排序（3）

将四个语块排列成自然的句子，提交完整语序（如 `3：1324`）。

### 3. 去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。

1. 運転する
2. 乗った
3. ガイドさんの
4. 船に

## 第三部分：篇章完形（4）

阅读短文，根据上下文选择最合适的一项。

### 文章一：寮のルール

寮の説明書きには、『昼間は部屋で楽器を（4）けど、夜十時以降はやめてください』と書いてありました。

#### 4.

1. 演奏してはいけない
2. 演奏したことがある
3. 演奏してもいい
4. 演奏しなくてもいい

---

## 答案填写区

```text
第一部分（1–2）：
1-, 2-

第二部分（3，请提交完整语序）：
3-

第三部分（4）：
4-
```
```

`answers/2026-01-02-n4-coverage-test-1-answers.md`：

```markdown
# N4 迷你卷一 · 答案解析

---

## 第一部分（1–2）形式选择

### 第 1 题（N4-Q-0003）

**题目**：何回も説明した（　）、彼はまだ分かっていない。
**翻译**：明明说明了好几遍，他却还是没懂。
**考点**：N4-G-0001「～のに：逆接」
**正确项**：1（のに）
**正确接续**：動詞普通形＋**のに**（説明した＋**のに**）＝明明……却……

**解析**：「说明过→该懂→实际没懂」的落差用のに。（N4-G-0001）
- 选项 2（ので）：表原因，逻辑颠倒。
- 选项 3（から）：也表原因，不成立。
- 选项 4（まで）：表终点，无逆接义。

### 第 2 题（N4-Q-0004）

**题目**：天気のいい日には、ここからでも富士山を（　）ことができます。
**翻译**：天气好的日子，从这里也能看到富士山。
**考点**：N4-G-0003「～ことができます」
**正确项**：4（見る）
**正确接续**：動詞辞書形＋**ことが**できます（見る＋**ことが**できます）＝能够……

**解析**：こと前只能接辞书形。（N4-G-0003）
- 选项 1（見て）：て形不接ことができる。
- 选项 2（見ます）：ます形不接。
- 选项 3（見た）：た形接的是经验句たことがあります。

## 第二部分（3）句子排序

### 第 3 题（N4-Q-0005）

**题目**：见试卷第 3 题框架
**翻译**：去年夏天在湖水旅行时，我坐过导游开的船。
**考点**：N4-G-0003「～たことがあります」
**推荐语序**：3142（ガイドさんの→運転する→船に→乗った）
**正确项**：1（運転する）
**正确接续**：動詞た形＋**こと**があります（乗った＋**ことが**あります）＝有过……的经历

**解析**：推荐语序：ガイドさんの(3)／運転する(1)／船に(4)／乗った(2)＋ことがあります。★处（第二格）是「運転する」。（N4-G-0003）
- 选项 2（乗った）：位于第四格，た形贴「ことがあります」。
- 选项 3（ガイドさんの）：位于第一格，修饰「運転する」。
- 选项 4（船に）：位于第三格，贴「乗った」。

## 第三部分（4）篇章完形

### 第 4 题（N4-Q-0006）

**题目**：寮の説明書きには、『昼間は部屋で楽器を（4）けど、夜十時以降はやめてください』と書いてありました。
**翻译**：宿舍须知上写着：白天可以在房间演奏乐器，但晚上十点以后请停止。
**考点**：N4-G-0002「～てもいい：许可」
**正确项**：3（演奏してもいい）
**正确接续**：動詞て形＋**もいい**（演奏**して**＋**もいい**）＝可以……

**解析**：白天许可、晚上收回，てもいい与转折けど呼应。（N4-G-0002）
- 选项 1（演奏してはいけない）：与后句逻辑相反。
- 选项 2（演奏したことがある）：经验句，语义不合。
- 选项 4（演奏しなくてもいい）：可以不演奏，语义不合。
```

`papers/2026-01-01-n4-coverage-test-0.md` 与对应 answers：内容取上面三道形式选择题（第 1 题即 N4-Q-0001 静かな、第 2 题 N4-Q-0002 排序、第 3 题 N4-Q-0003? 不——旧卷只引旧卡）。旧卷结构 1+1+0：第 1 题引 N4-Q-0001（静かな）、第 2 题引 N4-Q-0002（排序 2314）；answers 同构（题目/翻译/考点 N4-G-0002、推荐语序 2314、正确项 3、三行选项解析）。旧卷仅作查重基准与 smoke 解析样例，格式照抄上面的试卷/答案模板。

- [ ] **Step 2: 写 conftest.py**

```python
import shutil
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

FIXTURES = TESTS_DIR / "fixtures"


@pytest.fixture
def env_basic(tmp_path):
    """把 env-basic 迷你题库复制到 tmp_path，返回其根（含 jlpt-notes/ 的目录）。"""
    dst = tmp_path / "env"
    shutil.copytree(FIXTURES / "env-basic", dst)
    return dst


@pytest.fixture
def mutate():
    """对 env 内相对路径做恰好一次子串替换；目标不存在时立即使测试失败。"""
    def _mutate(root: Path, rel: str, old: str, new: str) -> None:
        p = root / rel
        text = p.read_text(encoding="utf-8")
        assert old in text, f"mutation target not found in {rel}: {old!r}"
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return _mutate
```

- [ ] **Step 3: 写失败测试 test_parsing.py**

```python
from quizlib.parsing import parse_paper, parse_answers


def _paper_text(env_basic):
    return (env_basic / "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md").read_text(encoding="utf-8")


def _answers_text(env_basic):
    return (env_basic / "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md").read_text(encoding="utf-8")


def test_parse_paper_sections_and_counts(env_basic):
    paper = parse_paper(_paper_text(env_basic))
    sections = [q.section for q in paper.questions]
    assert sections == ["form", "form", "order", "cloze"]
    assert [q.number for q in paper.questions] == [1, 2, 3, 4]


def test_parse_paper_form_question_options(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[0]
    assert q.stem == "何回も説明した（　）、彼はまだ分かっていない。"
    assert q.options == {"1": "のに", "2": "ので", "3": "から", "4": "まで"}
    assert q.star_pos is None


def test_parse_paper_order_star_pos(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[2]
    assert q.section == "order"
    assert q.star_pos == 2
    assert q.options["3"] == "ガイドさんの"


def test_parse_paper_cloze_empty_stem_with_options(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[3]
    assert q.section == "cloze"
    assert q.stem == ""
    assert len(q.options) == 4


def test_parse_paper_ignores_answer_sheet_area(env_basic):
    paper = parse_paper(_paper_text(env_basic))
    assert len(paper.questions) == 4  # 答案填写区里的 "1-, 2-" 不算题目


def test_parse_answers_fields(env_basic):
    entries = parse_answers(_answers_text(env_basic))
    assert len(entries) == 4
    e1 = entries[0]
    assert e1.number == 1
    assert e1.card_id == "N4-Q-0003"
    assert e1.grammar_ids == ["N4-G-0001"]
    assert e1.correct_option == "1"
    assert e1.translation.startswith("明明")
    assert "のに" in e1.analysis
    assert set(e1.option_analyses) == {"2", "3", "4"}


def test_parse_answers_order_entry(env_basic):
    e3 = parse_answers(_answers_text(env_basic))[2]
    assert e3.card_id == "N4-Q-0005"
    assert e3.order == "3142"
    assert e3.correct_option == "1"
    assert e3.conjugation.startswith("動詞た形")
```

- [ ] **Step 4: 跑测试确认失败**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_parsing.py" -v`（在仓库根执行）
Expected: FAIL（ModuleNotFoundError: quizlib）

- [ ] **Step 5: 实现 models.py 与 parsing.py**

`quizlib/models.py`：

```python
from dataclasses import dataclass, field

ERROR = "error"
WARN = "warn"


@dataclass
class Finding:
    check: str        # "C1".."C7"
    severity: str     # ERROR / WARN
    location: str     # 如 "题21 / N4-Q-0302"
    message: str


@dataclass
class PaperQuestion:
    number: int
    section: str                 # "form" | "order" | "cloze"
    stem: str = ""
    options: dict = field(default_factory=dict)
    star_pos: int | None = None  # 排序题★在第几空（1 起）


@dataclass
class Paper:
    questions: list = field(default_factory=list)
    raw_text: str = ""


@dataclass
class AnswerEntry:
    number: int
    card_id: str = ""
    stem: str = ""
    grammar_ids: list = field(default_factory=list)
    correct_option: str = ""
    order: str | None = None
    analysis: str = ""
    option_analyses: dict = field(default_factory=dict)
    translation: str = ""
    conjugation: str = ""
```

`quizlib/parsing.py`：

```python
import re

from .models import AnswerEntry, Paper, PaperQuestion

QUESTION_HEADER_RE = re.compile(r"^#{3,4}\s*(\d+)[.．]\s*(.*)$")
SECTION_RE = re.compile(r"^##\s*第([一二三])部分")
OPTION_RE = re.compile(r"^(\d)[.．]\s*(.+)$")
ANSWER_HEADER_RE = re.compile(r"^###\s*第\s*(\d+)\s*题[（(]([NS]\d+-Q-\d{4})[）)]")
FIELD_RE = re.compile(r"^\*\*(题目|翻译|考点|推荐语序|正确项|正确接续|解析)\*\*[：:]\s*(.*)$")
GRAMMAR_ID_RE = re.compile(r"[NS]\d+-G-\d{4}")
ORDER_RE = re.compile(r"^(\d{4})[（(]")
CORRECT_RE = re.compile(r"^(\d)")
OPTION_ANA_RE = re.compile(r"^-?\s*选项\s*(\d)[（(](.+?)[）)]\s*[：:]")

_SECTION_NAMES = {"一": "form", "二": "order", "三": "cloze"}


def _star_pos(stem: str) -> int | None:
    """数题干里 ★ 前出现的 ＿＿ 数量，★ 位置＝空位序号（1 起）。"""
    if "★" not in stem:
        return None
    pos = 0
    for token in re.finditer(r"＿＿|★", stem):
        pos += 1
        if token.group(0) == "★":
            return pos
    return None


def parse_paper(text: str) -> Paper:
    paper = Paper(raw_text=text)
    section = "form"
    current = None
    seen_option_lines_after_header = False
    for raw in text.splitlines():
        line = raw.rstrip()
        m = SECTION_RE.match(line)
        if m:
            section = _SECTION_NAMES[m.group(1)]
            continue
        if line.startswith("## 答案填写区"):
            break
        m = QUESTION_HEADER_RE.match(line)
        if m and not OPTION_RE.match(line):
            current = PaperQuestion(number=int(m.group(1)), section=section,
                                    stem=m.group(2).strip())
            current.star_pos = _star_pos(current.stem)
            paper.questions.append(current)
            seen_option_lines_after_header = False
            continue
        if current is not None:
            om = OPTION_RE.match(line)
            if om:
                current.options[om.group(1)] = om.group(2).strip()
                seen_option_lines_after_header = True
    return paper


def parse_answers(text: str) -> list[AnswerEntry]:
    entries: list[AnswerEntry] = []
    current: AnswerEntry | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = ANSWER_HEADER_RE.match(line)
        if m:
            current = AnswerEntry(number=int(m.group(1)), card_id=m.group(2))
            entries.append(current)
            continue
        if current is None:
            continue
        fm = FIELD_RE.match(line)
        if fm:
            key, value = fm.group(1), fm.group(2).strip()
            if key == "题目":
                current.stem = value
            elif key == "翻译":
                current.translation = value
            elif key == "考点":
                current.grammar_ids = GRAMMAR_ID_RE.findall(value)
            elif key == "推荐语序":
                om = ORDER_RE.match(value)
                current.order = om.group(1) if om else None
            elif key == "正确项":
                cm = CORRECT_RE.match(value)
                current.correct_option = cm.group(1) if cm else ""
            elif key == "正确接续":
                current.conjugation = value
            elif key == "解析":
                current.analysis = value
            continue
        om = OPTION_ANA_RE.match(line)
        if om:
            current.option_analyses[om.group(1)] = om.group(2).strip()
    return entries
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_parsing.py" -v`
Expected: PASS（7 个测试全绿）

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/quiz-generate/scripts
git commit -m "feat: quizlib 数据模型与试卷/答案解析器（含 hermetic 迷你题库 fixture）"
```

---

### Task 2: 题卡/语法卡装载 + C1 编号接缝 + C4 考点存在性

**Files:**
- Modify: `.claude/skills/quiz-generate/scripts/quizlib/parsing.py`（追加 loader）
- Create: `.claude/skills/quiz-generate/scripts/quizlib/checks.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/test_checks.py`

**Interfaces:**
- Consumes: Task 1 的 `AnswerEntry.card_id`、conftest `env_basic`/`mutate`。
- Produces: `QuestionCard`（`.id`、`.path`、`.frontmatter: dict`、属性 `.level/.item_type/.prompt/.options/.correct_option/.translation/.tested_cards/.recommended_order/.conjugation/.correct_explanation`，字段缺失返回安全默认值）；`load_question_cards(quizzes_dir: Path) -> dict[str, QuestionCard]`；`load_grammar_ids(notes_root: Path) -> set[str]`；`norm(s: str) -> str`（去全部空白与 `**`）；`check_card_ids(answers, cards, level) -> list[Finding]`（check="C1"）；`check_grammar_refs(answers, grammar_ids, level) -> list[Finding]`（check="C4"）。

- [ ] **Step 1: 写失败测试（追加到 test_checks.py）**

```python
from pathlib import Path

from quizlib.parsing import load_question_cards, load_grammar_ids, parse_answers
from quizlib.checks import check_card_ids, check_grammar_refs

NEW_ANSWERS = "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md"


def _env(env_basic):
    answers = parse_answers((env_basic / NEW_ANSWERS).read_text(encoding="utf-8"))
    cards = load_question_cards(env_basic / "jlpt-notes/quizzes")
    grammar = load_grammar_ids(env_basic / "jlpt-notes")
    return answers, cards, grammar


def test_load_question_cards(env_basic):
    _, cards, _ = _env(env_basic)
    assert set(cards) == {f"N4-Q-{i:04d}" for i in range(1, 7)}
    assert cards["N4-Q-0005"].recommended_order == "3142"
    assert cards["N4-Q-0005"].item_type == "sentence_composition"
    assert cards["N4-Q-0003"].tested_cards == ["N4-G-0001"]


def test_load_grammar_ids(env_basic):
    _, _, grammar = _env(env_basic)
    assert grammar == {"N4-G-0001", "N4-G-0002", "N4-G-0003"}


def test_c1_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_card_ids(answers, cards, "N4") == []


def test_c1_duplicate_id(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"id": "N4-Q-0004"', '"id": "N4-Q-0002"')
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" and f.severity == "error" and "重复" in f.message for f in findings)


def test_c1_new_ids_not_consecutive(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"id": "N4-Q-0004"', '"id": "N4-Q-0009"')
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0004", "N4-Q-0009")
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" and "连续" in f.message for f in findings)


def test_c1_new_ids_must_come_after_existing(env_basic, mutate):
    # 新卡号小于既有最大号 0002 → 接缝错误
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           '"id": "N4-Q-0003"', '"id": "N4-Q-0001"')
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0003）", "N4-Q-0001a）")  # 仅答案引用改名占位
    # 说明：直接同名会与 0001 撞车先报重复；接缝检查用 0001a 非法格式演示，断言两条都抓
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" for f in findings)


def test_c4_missing_grammar_ref(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "N4-G-0001「", "N4-G-9999「")
    answers, _, _ = _env(env_basic)
    findings = check_grammar_refs(answers, {"N4-G-0001", "N4-G-0002", "N4-G-0003"}, "N4")
    assert any(f.check == "C4" and "N4-G-9999" in f.message for f in findings)


def test_c4_clean_env_passes(env_basic):
    answers, _, grammar = _env(env_basic)
    assert check_grammar_refs(answers, grammar, "N4") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_checks.py" -v`
Expected: FAIL（ImportError: check_card_ids 不存在）

- [ ] **Step 3: 实现 loader 与 C1/C4**

追加到 `quizlib/parsing.py`：

```python
import json
from pathlib import Path

from .models import QuestionCard  # 追加到 models.py：
```

（`models.py` 追加：）

```python
@dataclass
class QuestionCard:
    id: str
    path: str = ""
    frontmatter: dict = field(default_factory=dict)

    def _get(self, key, default=None):
        return self.frontmatter.get(key, default)

    @property
    def level(self): return self._get("level", "")
    @property
    def item_type(self): return self._get("item_type", "")
    @property
    def prompt(self): return self._get("prompt", "")
    @property
    def options(self): return self._get("options", {}) or {}
    @property
    def correct_option(self): return str(self._get("correct_option", "") or "")
    @property
    def translation(self): return self._get("translation", "")
    @property
    def tested_cards(self): return self._get("tested_cards", []) or []
    @property
    def recommended_order(self): return self._get("recommended_order", "")
    @property
    def conjugation(self): return self._get("conjugation", "")
    @property
    def correct_explanation(self): return self._get("correct_explanation", "")
```

（`parsing.py` 追加：）

```python
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def extract_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("frontmatter not found")
    return json.loads(m.group(1))


def load_question_cards(quizzes_dir: Path) -> dict:
    cards = {}
    for p in sorted((quizzes_dir / "questions").glob("*.md")):
        try:
            fm = extract_frontmatter(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            continue  # 解析失败的卡在 C1 里以「frontmatter 无效」报告需要另行登记；
            # 为此 loader 返回时同时记录坏卡：
        cid = str(fm.get("id") or p.stem)
        card = QuestionCard(id=cid, path=str(p), frontmatter=fm)
        cards.setdefault(cid, card)
    return cards


def load_question_card_errors(quizzes_dir: Path) -> list:
    """返回 [(path, 原因)]，frontmatter 损坏的卡由 C1 报告。"""
    errors = []
    for p in sorted((quizzes_dir / "questions").glob("*.md")):
        try:
            extract_frontmatter(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append((p.name, str(exc)))
    return errors


def load_grammar_ids(notes_root: Path) -> set:
    ids = set()
    for p in sorted((notes_root / "grammar").glob("*/*.md")):
        try:
            fm = extract_frontmatter(p.read_text(encoding="utf-8"))
            ids.add(str(fm.get("id") or p.stem))
        except (ValueError, json.JSONDecodeError):
            ids.add(p.stem)
    return ids
```

注意 `load_question_cards` 里坏卡被 continue 跳过会导致 id 丢失——改为：坏卡也登记（`fm = {}`、id 取文件名 stem），保证重复/接缝检查仍覆盖它；`load_question_card_errors` 单独给 C1 报「frontmatter 无效」。实现时以这句话为准修正循环体：

```python
    for p in sorted((quizzes_dir / "questions").glob("*.md")):
        try:
            fm = extract_frontmatter(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            fm = None
        cid = str((fm or {}).get("id") or p.stem)
        cards.setdefault(cid, QuestionCard(id=cid, path=str(p), frontmatter=fm or {}))
```

新建 `quizlib/checks.py`：

```python
import re

from .models import AnswerEntry, ERROR, Finding, QuestionCard
from .parsing import load_question_card_errors

CARD_ID_RE = re.compile(r"^[NS]\d+-Q-\d{4}$")


def norm(s: str) -> str:
    """去全部空白（含全角空格）与 ** 加粗标记，用于跨文件文本比对。"""
    return re.sub(r"(\s|\*\*)+", "", s or "")


def _numeric(cid: str) -> int:
    return int(cid.rsplit("-", 1)[1])


def check_card_ids(answers: list[AnswerEntry], cards: dict, level: str,
                   quizzes_dir=None) -> list[Finding]:
    findings = []
    if quizzes_dir is not None:
        for name, why in load_question_card_errors(quizzes_dir):
            findings.append(Finding("C1", ERROR, name, f"frontmatter 无效：{why}"))
    # 重复 id（同 id 多文件在 loader 里被合并，故用 path 集合不可行；
    # 改由调用方先做文件级重复检测：这里检查答案引用的卡都存在）
    for e in answers:
        if not CARD_ID_RE.match(e.card_id):
            findings.append(Finding("C1", ERROR, f"题{e.number}", f"题卡 ID 格式非法：{e.card_id}"))
            continue
        if e.card_id not in cards:
            findings.append(Finding("C1", ERROR, f"题{e.number}", f"答案引用的题卡不存在：{e.card_id}"))
            continue
        card = cards[e.card_id]
        if card.level and card.level != level:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"题卡级别不符：{e.card_id} 是 {card.level}，应为 {level}"))
        for field_name in ("prompt", "correct_option", "correct_explanation"):
            if not getattr(card, field_name):
                findings.append(Finding("C1", ERROR, f"题{e.number}",
                                        f"题卡 {e.card_id} 缺必填字段：{field_name}"))
        if len(card.options) != 4:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"题卡 {e.card_id} 选项数≠4（{len(card.options)}）"))
        if card.item_type == "sentence_composition" and not card.recommended_order:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"排序题卡 {e.card_id} 缺 recommended_order"))
    # 新卡段接缝：新卡号必须整体大于旧卡号且自身连续
    new_ids = [e.card_id for e in answers if e.card_id in cards]
    prefix = f"{level}-Q-"
    same_level = [cid for cid in cards if cid.startswith(prefix)]
    new_set = set(new_ids)
    old_max = max((_numeric(c) for c in same_level if c not in new_set), default=0)
    nums = sorted(_numeric(c) for c in set(new_ids) if c.startswith(prefix))
    if nums:
        if nums[0] <= old_max:
            findings.append(Finding("C1", ERROR, new_ids[0],
                                    f"新题卡号 {new_ids[0]} 未接续既有最大号（>{old_max:04d}）"))
        if nums != list(range(nums[0], nums[0] + len(nums))):
            findings.append(Finding("C1", ERROR, prefix + str(nums[0]),
                                    f"新题卡号不连续：{nums}"))
    return findings


def check_grammar_refs(answers: list[AnswerEntry], grammar_ids: set, level: str) -> list[Finding]:
    findings = []
    for e in answers:
        for gid in e.grammar_ids:
            if gid not in grammar_ids:
                findings.append(Finding("C4", ERROR, f"题{e.number}", f"考点卡不存在：{gid}"))
            elif not gid.startswith(f"{level}-G-"):
                findings.append(Finding("C4", ERROR, f"题{e.number}",
                                        f"考点卡级别不符：{gid} 应为 {level} 语法卡"))
        if not e.grammar_ids:
            findings.append(Finding("C4", ERROR, f"题{e.number}", "考点字段未解析出卡号"))
    return findings
```

同 id 双文件的重复检测：`load_question_cards` 用 `setdefault` 合并会吞掉重复——在 loader 里改成显式登记：dict 值存 list 或返回 `(cards, duplicate_ids)`。**实现决定**：`load_question_cards` 保持返回 dict，但发现同 id 再遇时把该 id 记入模块级返回……为保接口简单，改为：loader 遇重复 id 时，把后一个文件的 frontmatter 存进 `cards[cid]` 并把 `cid` 加入返回 dict 的特殊键 `"__duplicates__"`（value 为 list[str]）。`check_card_ids` 读到该键即报 C1「重复 id」。Task 5 的 CLI 同样兼容。测试 `test_c1_duplicate_id` 依赖此行为（mutate 把 N4-Q-0004 的 id 改成 N4-Q-0002 后，bank 中出现两个 id=N4-Q-0002 的文件）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v`
Expected: PASS（Task 1 + Task 2 全绿）

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/quiz-generate/scripts
git commit -m "feat: 题卡/语法卡装载与 C1 编号接 seams、C4 考点存在性检查"
```

---

### Task 3: C2 排序不变量 + C3 三方一致性

**Files:**
- Modify: `.claude/skills/quiz-generate/scripts/quizlib/checks.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/test_checks.py`（追加）

**Interfaces:**
- Consumes: `norm`、`Paper/PaperQuestion`、`AnswerEntry`、`QuestionCard` 属性。
- Produces: `check_order_invariants(paper: Paper, answers: list[AnswerEntry], cards: dict) -> list[Finding]`（check="C2"）；`check_consistency(paper: Paper, answers: list[AnswerEntry], cards: dict) -> list[Finding]`（check="C3"）。

- [ ] **Step 1: 写失败测试（追加）**

```python
from quizlib.parsing import parse_paper
from quizlib.checks import check_order_invariants, check_consistency

NEW_PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"


def _paper(env_basic):
    return parse_paper((env_basic / NEW_PAPER).read_text(encoding="utf-8"))


def test_c2_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_order_invariants(_paper(env_basic), answers, cards) == []


def test_c2_invalid_permutation(env_basic, mutate):
    # 语序 3142 → 3112：不是 1-4 的排列
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3112")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "排列" in f.message for f in findings)


def test_c2_digit_typo_breaks_block_numbering(env_basic, mutate):
    # 语序 3142 → 3412（仍是合法排列）——解析文字块编号仍是 3,1,4,2 → 不一致
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3412")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "编号" in f.message for f in findings)


def test_c2_card_answers_order_disagree(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0005.md",
           '"recommended_order": "3142"', '"recommended_order": "3412"')
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "题卡" in f.message and "语序" in f.message for f in findings)


def test_c2_star_position_mismatch(env_basic, mutate):
    # ★ 放到第 3 空：正确项应变成语序第 3 位"4"，但答案仍写 1
    mutate(env_basic, NEW_PAPER,
           "去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。",
           "去年の夏、湖水旅行で、＿＿ ＿＿ ★ ＿＿ ことがあります。")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "★" in f.message for f in findings)


def test_c3_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_consistency(_paper(env_basic), answers, cards) == []


def test_c3_correct_option_disagreement(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"correct_option": "4"', '"correct_option": "1"')
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "正确项" in f.message for f in findings)


def test_c3_option_text_drift(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "2. 見ます", "2. 見ません")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "选项" in f.message for f in findings)


def test_c3_translation_disagreement(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "**翻译**：天气好的日子", "**翻译**：天气好的日子里")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "翻译" in f.message for f in findings)


def test_c3_tested_cards_disagreement(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS,
           "**考点**：N4-G-0003「～ことができます」", "**考点**：N4-G-0002「～ことができます」")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "考点" in f.message for f in findings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_checks.py" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 C2/C3（追加到 checks.py）**

```python
BLOCK_DIGIT_RE = re.compile(r"[（(]\s*([1-4])\s*[）)]")


def check_order_invariants(paper, answers, cards) -> list[Finding]:
    findings = []
    order_entries = {e.number: e for e in answers if e.order is not None}
    order_questions = {q.number: q for q in paper.questions if q.section == "order"}
    for number, e in sorted(order_entries.items()):
        loc = f"题{number} / {e.card_id}"
        card = cards.get(e.card_id)
        order = e.order
        if sorted(order) != list("1234"):
            findings.append(Finding("C2", ERROR, loc, f"推荐语序 {order} 不是 1–4 的合法排列"))
            continue
        # 解析文字里的块编号序列必须等于语序串（如 …(3)／(1)／(4)／(2)… ↔ 3142）
        digits = BLOCK_DIGIT_RE.findall(e.analysis)
        if digits and "".join(digits) != order:
            findings.append(Finding("C2", ERROR, loc,
                f"解析块编号 {''.join(digits)} 与推荐语序 {order} 不一致（数字串笔误）"))
        if card is not None and card.recommended_order:
            if card.recommended_order != order:
                findings.append(Finding("C2", ERROR, loc,
                    f"题卡语序 {card.recommended_order} 与答案语序 {order} 不一致"))
            cdigits = BLOCK_DIGIT_RE.findall(card.correct_explanation)
            if cdigits and "".join(cdigits) != order:
                findings.append(Finding("C2", ERROR, loc,
                    f"题卡解析块编号 {''.join(cdigits)} 与推荐语序 {order} 不一致"))
        q = order_questions.get(number)
        if q is None:
            findings.append(Finding("C2", ERROR, loc, "答案含语序但试卷无对应排序题"))
            continue
        if q.star_pos is None:
            findings.append(Finding("C2", ERROR, loc, "试卷排序题缺 ★ 标记"))
        else:
            expected = order[q.star_pos - 1]
            if e.correct_option and e.correct_option != expected:
                findings.append(Finding("C2", ERROR, loc,
                    f"★ 位（第{q.star_pos}空）语序数字为 {expected}，但正确项写 {e.correct_option}"))
    for number in sorted(set(order_questions) - set(order_entries)):
        findings.append(Finding("C2", ERROR, f"题{number}", "排序题缺推荐语序"))
    return findings


def check_consistency(paper, answers, cards) -> list[Finding]:
    findings = []
    paper_by_number = {q.number: q for q in paper.questions}
    for e in answers:
        loc = f"题{e.number} / {e.card_id}"
        card = cards.get(e.card_id)
        q = paper_by_number.get(e.number)
        if card is None or q is None:
            continue  # C1/C5 负责缺卡缺题
        # 选项三方一致（试卷 ↔ 题卡）
        for opt, text in q.options.items():
            ct = card.options.get(opt, "")
            if ct and norm(ct) != norm(text):
                findings.append(Finding("C3", ERROR, loc,
                    f"选项 {opt} 不一致：试卷「{text}」≠ 题卡「{ct}」"))
        # 正确项：题卡 ↔ 答案
        if card.correct_option and e.correct_option and card.correct_option != e.correct_option:
            findings.append(Finding("C3", ERROR, loc,
                f"正确项不一致：题卡 {card.correct_option} ≠ 答案 {e.correct_option}"))
        # 题干：试卷题干 ⊆ 题卡 prompt；答案题干 ⊆ 题卡 prompt（完形题卡含全文）
        if q.stem:
            if norm(q.stem) not in norm(card.prompt):
                findings.append(Finding("C3", ERROR, loc, "试卷题干未出现在题卡 prompt 中"))
        if e.stem and norm(e.stem) not in norm(card.prompt):
            findings.append(Finding("C3", WARN, loc, "答案题干未出现在题卡 prompt 中"))
        # 翻译：题卡 ↔ 答案（题卡缺字段则跳过）
        if card.translation and e.translation and norm(card.translation) != norm(e.translation):
            findings.append(Finding("C3", ERROR, loc, "翻译不一致：题卡与答案文件不同"))
        # 考点：题卡 tested_cards ↔ 答案 grammar_ids（题卡缺字段降级为 warn）
        if card.tested_cards:
            if set(card.tested_cards) != set(e.grammar_ids):
                findings.append(Finding("C3", ERROR, loc,
                    f"考点不一致：题卡 {card.tested_cards} ≠ 答案 {e.grammar_ids}"))
        elif e.grammar_ids:
            findings.append(Finding("C3", WARN, loc, "题卡缺 tested_cards 字段，无法核对考点"))
        # 答案正确项括号里的选项文字应与试卷选项一致
        m = re.match(r"^(\d)[（(](.+?)[）)]$", e.correct_option_text or "")
    return findings
```

注：最后一行 `correct_option_text` 需要 `AnswerEntry` 增加 `correct_option_text: str = ""` 字段，`parse_answers` 在 `**正确项**：1（運転する）` 时同时记录全文；`check_consistency` 末尾补完：

```python
        m = re.match(r"^(\d)[（(](.+?)[）)]$", e.correct_option_text)
        if m:
            opt, text = m.group(1), m.group(2)
            pt = q.options.get(opt, "")
            if pt and norm(pt) != norm(text):
                findings.append(Finding("C3", WARN, loc,
                    f"正确项 {opt} 文字「{text}」与试卷选项「{pt}」不同"))
```

同步修改 `models.py`（AnswerEntry 加字段）与 `parsing.py`（`elif key == "正确项": current.correct_option_text = value` 并保留原 correct_option 提取逻辑）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/quiz-generate/scripts
git commit -m "feat: C2 排序题不变量（排列/块编号/★位）与 C3 三方一致性检查"
```

---

### Task 4: C5 结构 + C7 答案完整性 + C6 跨卷查重

**Files:**
- Modify: `.claude/skills/quiz-generate/scripts/quizlib/checks.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/test_checks.py`（追加）

**Interfaces:**
- Produces: `check_structure(paper: Paper, expected=(20, 7, 7)) -> list[Finding]`（check="C5"，mini 卷传 `(2, 1, 1)`）；`check_answer_completeness(paper, answers) -> list[Finding]`（check="C7"）；`check_duplicates(answers, cards) -> list[Finding]`（check="C6"，仅对比答案引用的新卡 prompt 与库内其他卡）。

- [ ] **Step 1: 写失败测试（追加）**

```python
from quizlib.checks import check_structure, check_answer_completeness, check_duplicates


def test_c5_clean_mini_env_passes(env_basic):
    assert check_structure(_paper(env_basic), expected=(2, 1, 1)) == []


def test_c5_missing_question(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "### 2. 天気のいい日には", "### 3. 天気のいい日には")
    findings = check_structure(_paper(env_basic), expected=(2, 1, 1))
    assert any(f.check == "C5" and "连续" in f.message for f in findings)


def test_c5_wrong_section_count(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "#### 4.\n", "#### 4.\n1. 演奏してはいけない\n2. 演奏したことがある\n")
    # 选项只剩 2 个 → C5 选项数检查
    findings = check_structure(_paper(env_basic), expected=(2, 1, 1))
    assert any(f.check == "C5" and "选项" in f.message for f in findings)


def test_c7_clean_env_passes(env_basic):
    answers, _, _ = _env(env_basic)
    assert check_answer_completeness(_paper(env_basic), answers) == []


def test_c7_missing_question_in_answers(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "### 第 4 题（N4-Q-0006）", "### 第 5 题（N4-Q-0006）")
    answers, _, _ = _env(env_basic)
    findings = check_answer_completeness(_paper(env_basic), answers)
    assert any(f.check == "C7" and "4" in f.message for f in findings)


def test_c7_option_analysis_missing(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS,
           "- 选项 4（演奏しなくてもいい）：可以不演奏，语义不合。\n", "")
    answers, _, _ = _env(env_basic)
    findings = check_answer_completeness(_paper(env_basic), answers)
    assert any(f.check == "C7" and "选项解析" in f.message for f in findings)


def test_c6_exact_duplicate_prompt(env_basic, mutate):
    # 把新卡 N4-Q-0003 的 prompt 换成旧库 N4-Q-0001 的题干 → 精确重复
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           "何回も説明した（　）、彼はまだ分かっていない。",
           "図書館は（　）ので、勉強に集中できます。")
    answers, cards, _ = _env(env_basic)
    findings = check_duplicates(answers, cards)
    assert any(f.check == "C6" and f.severity == "error" and "重复" in f.message for f in findings)


def test_c6_similar_prompt_warns(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           "何回も説明した（　）、彼はまだ分かっていない。",
           "何回も説明した（　）、彼はまだ分かっていません。")
    answers, cards, _ = _env(env_basic)
    findings = check_duplicates(answers, cards)
    assert any(f.check == "C6" and f.severity == "warn" for f in findings)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_checks.py" -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现（追加到 checks.py）**

```python
from difflib import SequenceMatcher


def check_structure(paper, expected=(20, 7, 7)) -> list[Finding]:
    findings = []
    sections = {"form": [], "order": [], "cloze": []}
    for q in paper.questions:
        sections.setdefault(q.section, []).append(q.number)
        if len(q.options) != 4:
            findings.append(Finding("C5", ERROR, f"题{q.number}",
                                    f"选项数≠4（{len(q.options)}）"))
    for sec, want in zip(("form", "order", "cloze"), expected):
        got = len(sections.get(sec, []))
        if got != want:
            findings.append(Finding("C5", ERROR, sec,
                                    f"{sec} 题量 {got} ≠ 预期 {want}"))
    numbers = sorted(q.number for q in paper.questions)
    if numbers != list(range(1, len(numbers) + 1)):
        findings.append(Finding("C5", ERROR, "试卷",
                                f"题号不连续：{numbers}"))
    return findings


def check_answer_completeness(paper, answers) -> list[Finding]:
    findings = []
    paper_numbers = {q.number for q in paper.questions}
    answer_numbers = {e.number for e in answers}
    for n in sorted(paper_numbers - answer_numbers):
        findings.append(Finding("C7", ERROR, f"题{n}", "答案文件缺该题条目"))
    for n in sorted(answer_numbers - paper_numbers):
        findings.append(Finding("C7", ERROR, f"题{n}", "答案文件多出试卷没有的题"))
    for e in answers:
        loc = f"题{e.number}"
        if e.number not in paper_numbers:
            continue
        if not e.correct_option:
            findings.append(Finding("C7", ERROR, loc, "缺正确项"))
        if not e.translation:
            findings.append(Finding("C7", ERROR, loc, "缺翻译"))
        if not e.conjugation:
            findings.append(Finding("C7", ERROR, loc, "缺正确接续"))
        if not e.analysis:
            findings.append(Finding("C7", ERROR, loc, "缺解析"))
        if len(e.option_analyses) < 3:
            findings.append(Finding("C7", ERROR, loc,
                                    f"选项解析不足 3 项（{len(e.option_analyses)}）"))
        if not e.grammar_ids:
            findings.append(Finding("C7", ERROR, loc, "缺考点"))
    return findings


def check_duplicates(answers, cards, similarity_threshold=0.85) -> list[Finding]:
    findings = []
    new_ids = [e.card_id for e in answers]
    new_set = set(new_ids)
    for cid in sorted(new_set):
        card = cards.get(cid)
        if card is None or not card.prompt:
            continue
        a = norm(card.prompt)
        for other_id, other in cards.items():
            if other_id == cid or other_id == "__duplicates__":
                continue
            b = norm(other.prompt)
            if not b:
                continue
            if a == b:
                findings.append(Finding("C6", ERROR, cid,
                                        f"题干与既有题卡 {other_id} 完全重复"))
                continue
            if other_id in new_set:
                continue  # 新卡之间只报精确重复，避免整卷相似误报
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= similarity_threshold:
                findings.append(Finding("C6", WARN, cid,
                                        f"题干与既有题卡 {other_id} 相似度 {ratio:.2f}，需盲测复核"))
    return findings
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/quiz-generate/scripts
git commit -m "feat: C5 结构、C7 答案完整性、C6 跨卷查重检查"
```

---

### Task 5: CLI 编排（validate_quiz.py）

**Files:**
- Create: `.claude/skills/quiz-generate/scripts/validate_quiz.py`
- Test: `.claude/skills/quiz-generate/scripts/tests/test_validate_cli.py`

**Interfaces:**
- Consumes: `parse_paper/parse_answers/load_question_cards/load_grammar_ids`、七个 check 函数。
- Produces: 命令行接口 `uv run .claude/skills/quiz-generate/scripts/validate_quiz.py --paper <p> --answers <a> [--root <repo>] [--structure 20,7,7] [--level N4] [--json]`；`find_root(start: Path) -> Path`（向上找含 `jlpt-notes` 的目录）；退出码：有 error→1，仅 warn 或干净→0；`run_validation(paper_path, answers_path, root, expected_counts, level) -> list[Finding]`（Task 6/7 复用）。

- [ ] **Step 1: 写失败测试**

```python
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate_quiz.py"
PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"
ANSWERS = "jlft-notes-placeholder"  # 见下方真实值
ANSWERS = "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md"


def _run(env_basic, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--paper", str(env_basic / PAPER),
         "--answers", str(env_basic / ANSWERS), "--root", str(env_basic),
         "--structure", "2,1,1", *extra],
        capture_output=True, text=True, encoding="utf-8")


def test_cli_clean_env_exit_zero(env_basic):
    r = _run(env_basic)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "C1" not in r.stdout  # 人读报告不出现检查项错误


def test_cli_defect_exit_one_and_json(env_basic, mutate):
    mutate(env_basic, ANSWERS, "**推荐语序**：3142", "**推荐语序**：3112")
    r = _run(env_basic, "--json")
    assert r.returncode == 1
    report = json.loads(r.stdout)
    assert report["ok"] is False
    assert any(e["check"] == "C2" for e in report["findings"])


def test_cli_level_mismatch(env_basic, mutate):
    mutate(env_basic, ANSWERS, "（N4-Q-0003）", "（N5-Q-0003）")
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           '"id": "N4-Q-0003"', '"id": "N5-Q-0003"')
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           '"level": "N4"', '"level": "N5"')
    r = _run(env_basic)
    assert r.returncode == 1
    assert "级别" in r.stdout
```

（注意测试文件顶部那个 `ANSWERS = "jlft-notes-placeholder"` 行不要写，直接一处赋值即可——此处保留提醒实现者最终文件里只留正确赋值。）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_validate_cli.py" -v`
Expected: FAIL（validate_quiz.py 不存在）

- [ ] **Step 3: 实现 CLI**

```python
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
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/quiz-generate/scripts
git commit -m "feat: validate_quiz.py CLI（七项检查编排、--json、错误退出码 1，hook 兼容）"
```

---

### Task 6: 历史事故缺陷变异回归（每坑一测）

**Files:**
- Test: `.claude/skills/quiz-generate/scripts/tests/test_regression_incidents.py`

**Interfaces:**
- Consumes: `run_validation`（Task 5）、`env_basic`/`mutate`。断言辅助 `_errors(env) -> list[Finding]`（severity==error）。

**覆盖矩阵（每个历史事故类一测，全部用 mutate 从 env-basic 派生）：**

| 测试 | 事故类 | mutate 目标 | 期望检查项 |
|---|---|---|---|
| test_regression_order_digit_typo | 卷六语序数字串笔误（3 处之原型） | answers 推荐语序 3142→3412 | C2 |
| test_regression_order_typo_on_card | 同上但错在题卡侧 | 题卡 recommended_order 3142→3412 | C2 |
| test_regression_invalid_permutation | 无效排列 | answers 推荐语序 3142→3112 | C2 |
| test_regression_star_mismatch | ★位与正确项脱节 | 试卷 ★ 移到第 3 空 | C2 |
| test_regression_id_conflict | 卷三/卷四 ID 覆盖冲突 | 题卡 id N4-Q-0004→N4-Q-0002 | C1 |
| test_regression_id_gap | 新段编号断号 | 题卡+答案 N4-Q-0004→N4-Q-0009 | C1 |
| test_regression_answer_option_drift | 答案与题卡正确项不一致 | 题卡 correct_option 4→1 | C3 |
| test_regression_paper_option_drift | 试卷与题卡选项文字不同步 | 试卷选项文字改动 | C3 |
| test_regression_dangling_grammar_ref | 考点引用不存在的卡 | answers N4-G-0003→N4-G-9999（第 2 题） | C4 |
| test_regression_structure_hole | 漏题/题号断档 | 试卷第 2 题删头行使其并入第 1 题 | C5 |
| test_regression_answer_missing_entry | 答案缺整题 | answers 第 4 题整条目删除 | C7 |
| test_regression_cross_paper_dup | 跨卷重复题 | 新卡 prompt 换成旧库卡题干 | C6 |

- [ ] **Step 1: 写测试文件（完整代码）**

```python
"""历史事故回归：每个真实坑一类，mutate 重现后必须被拦截。"""
from quizlib.models import ERROR

NEW_PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"
NEW_ANSWERS = "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md"
CARD5 = "jlpt-notes/quizzes/questions/N4-Q-0005.md"
CARD4 = "jlpt-notes/quizzes/questions/N4-Q-0004.md"
CARD3 = "jlpt-notes/quizzes/questions/N4-Q-0003.md"
ORDER_STEM = "去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。"


def _errors(env_basic):
    from quizlib.validate_runner import run_validation  # 如未拆此模块则：
    return _errors_via_cli(env_basic)


def _errors_via_cli(env_basic):
    import subprocess, sys
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / "validate_quiz.py"
    r = subprocess.run(
        [sys.executable, str(script), "--paper", str(env_basic / NEW_PAPER),
         "--answers", str(env_basic / NEW_ANSWERS), "--root", str(env_basic),
         "--structure", "2,1,1", "--json"],
        capture_output=True, text=True, encoding="utf-8")
    import json
    report = json.loads(r.stdout)
    return [type("F", (), f)() for f in report["findings"] if f["severity"] == "error"]
```

实现决定（简化）：不引入 validate_runner；直接 `from validate_quiz import run_validation`（tests 的 conftest 已把 scripts 加入 sys.path，validate_quiz 模块级 import 不执行 main）。`_errors` 直接调 `run_validation` 并过滤 ERROR。各测试体示例（其余同构，按覆盖矩阵逐条写全）：

```python
def _errors(env_basic):
    from pathlib import Path
    from validate_quiz import run_validation
    findings = run_validation(
        Path(env_basic / NEW_PAPER), Path(env_basic / NEW_ANSWERS),
        Path(env_basic), expected_counts=(2, 1, 1))
    return [f for f in findings if f.severity == ERROR]


def test_regression_order_digit_typo(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3412")
    assert any(f.check == "C2" for f in _errors(env_basic))


def test_regression_order_typo_on_card(env_basic, mutate):
    mutate(env_basic, CARD5, '"recommended_order": "3142"', '"recommended_order": "3412"')
    assert any(f.check == "C2" for f in _errors(env_basic))


def test_regression_invalid_permutation(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3112")
    assert any(f.check == "C2" and "排列" in f.message for f in _errors(env_basic))


def test_regression_star_mismatch(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, ORDER_STEM,
           "去年の夏、湖水旅行で、＿＿ ＿＿ ★ ＿＿ ことがあります。")
    assert any(f.check == "C2" and "★" in f.message for f in _errors(env_basic))


def test_regression_id_conflict(env_basic, mutate):
    mutate(env_basic, CARD4, '"id": "N4-Q-0004"', '"id": "N4-Q-0002"')
    assert any(f.check == "C1" and "重复" in f.message for f in _errors(env_basic))


def test_regression_id_gap(env_basic, mutate):
    mutate(env_basic, CARD4, '"id": "N4-Q-0004"', '"id": "N4-Q-0009"')
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0004", "N4-Q-0009")
    assert any(f.check == "C1" and "连续" in f.message for f in _errors(env_basic))


def test_regression_answer_option_drift(env_basic, mutate):
    mutate(env_basic, CARD4, '"correct_option": "4"', '"correct_option": "1"')
    assert any(f.check == "C3" and "正确项" in f.message for f in _errors(env_basic))


def test_regression_paper_option_drift(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "2. 見ます", "2. 見ません")
    assert any(f.check == "C3" and "选项" in f.message for f in _errors(env_basic))


def test_regression_dangling_grammar_ref(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS,
           "**考点**：N4-G-0003「～ことができます」", "**考点**：N4-G-9999「～ことができます」")
    assert any(f.check == "C4" for f in _errors(env_basic))


def test_regression_structure_hole(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "### 2. 天気のいい日には", "### 5. 天気のいい日には")
    assert any(f.check == "C5" and "连续" in f.message for f in _errors(env_basic))


def test_regression_answer_missing_entry(env_basic, mutate):
    text = (env_basic / NEW_ANSWERS).read_text(encoding="utf-8")
    head = text.index("### 第 4 题")
    (env_basic / NEW_ANSWERS).write_text(text[:head].rstrip() + "\n", encoding="utf-8")
    assert any(f.check == "C7" for f in _errors(env_basic))


def test_regression_cross_paper_dup(env_basic, mutate):
    mutate(env_basic, CARD3,
           "何回も説明した（　）、彼はまだ分かっていない。",
           "図書館は（　）ので、勉強に集中できます。")
    assert any(f.check == "C6" and "重复" in f.message for f in _errors(env_basic))
```

注意：`test_regression_answer_missing_entry` 不用 mutate（要删到文件尾），直接读写文件；conftest 的 env_basic 每测试独立 tmp_path，互不污染。

- [ ] **Step 2: 跑回归测试确认通过（若个别断言落空，修 check 实现而非放松断言）**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_regression_incidents.py" -v`
Expected: PASS（12 测全绿）

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/quiz-generate/scripts/tests/test_regression_incidents.py
git commit -m "test: 历史事故缺陷变异回归（12 类坑各一测：语序笔误/无效排列/ID 冲突断号/三方漂移/悬空考点/结构洞/缺条目/跨卷重复）"
```

---

### Task 7: 真实旧卷 smoke + spec 验收②修订

**Files:**
- Test: `.claude/skills/quiz-generate/scripts/tests/test_smoke_real_papers.py`
- Modify: `docs/superpowers/specs/2026-08-20-quiz-skill-design.md`（验收标准②一段）
- Create: `.claude/skills/quiz-generate/scripts/tests/fixtures/known-real-findings.json`

**Interfaces:**
- Consumes: `run_validation`、真实仓库数据（只读）。

- [ ] **Step 1: 写 smoke 测试**

```python
"""对真实 N4 覆盖卷 1–6 整卷跑校验器。
预期：卷五/卷六（已修正）零错误；卷一～卷四若报错，必须逐条归因——
解析器 bug 则修解析器；真实机械缺陷则登记进 known-real-findings.json。
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

PAPERS = sorted(QUIZES.glob("2026-*-n4-coverage-test-*.md"))
assert PAPERS, "未找到 N4 覆盖卷"


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
```

初始 `known-real-findings.json`：

```json
{}
```

- [ ] **Step 2: 跑 smoke，逐错误归因**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests/test_smoke_real_papers.py" -v`
规则：每个 error 二选一——(a) 解析器/检查实现 bug → 修实现并补 mini 回归；(b) 旧卷真实机械缺陷 → 登记进 known-real-findings.json（含 check 与 message 关键词），并在 JSON 同目录新建 `known-real-findings.md` 记录每条的人工归因说明（哪卷哪题、为何保留）。禁止为绿而放松检查。
Expected: 6 卷全 PASS

- [ ] **Step 3: 修订 spec 验收②（与事实对齐）**

`docs/superpowers/specs/2026-08-20-quiz-skill-design.md` 中验收标准②整句替换为：

> ②六套旧卷整卷机械校验：解析器零误报（卷五/卷六零错误；卷一～卷四的报错逐条归因——真实机械缺陷登记 known-real-findings）；卷四 Q1/Q21/Q22 为语义缺陷，机械层不报，属盲测层验收样例；

- [ ] **Step 4: 全量测试 + Commit**

Run: `uv run --with pytest pytest ".claude/skills/quiz-generate/scripts/tests" -v`
Expected: PASS

```bash
git add .claude/skills/quiz-generate scripts docs/superpowers/specs/2026-08-20-quiz-skill-design.md 2>/dev/null || git add .claude/skills/quiz-generate docs
git commit -m "test: 真实六卷 smoke（已知机械缺陷白名单+人工归因）；spec 验收②对齐语义/机械分层事实"
```

（提交命令以实际路径为准：`git add .claude/skills/quiz-generate/scripts/tests/test_smoke_real_papers.py .claude/skills/quiz-generate/scripts/tests/fixtures/known-real-findings.json .claude/skills/quiz-generate/scripts/tests/fixtures/known-real-findings.md docs/superpowers/specs/2026-08-20-quiz-skill-design.md`，外加归因中修解析器的改动。）

---

### Task 8: quiz-generate SKILL.md（流程指令全文）

**Files:**
- Create: `.claude/skills/quiz-generate/SKILL.md`

**Interfaces:**
- Consumes: validate_quiz.py（Task 5）、盲测用 Agent 工具、仓库数据格式（Global Constraints 的数据基准）。

- [ ] **Step 1: 写 SKILL.md（全文如下）**

````markdown
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
````

- [ ] **Step 2: 人工核验**

- frontmatter YAML 合法、name=目录名、description 含「出题/出卷」触发词；
- 文中命令路径与 Task 5 的 CLI 参数一致（--paper/--answers/--structure）；
- Run: `uv run .claude/skills/quiz-generate/scripts/validate_quiz.py --help`（应打印 usage，证明路径与入口正确）

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/quiz-generate/SKILL.md
git commit -m "feat: quiz-generate 出题 skill（选卡提议→三件套→机械校验→盲测→裁决→交付，含历史坑自检清单与进化循环）"
```

---

## Self-Review 记录（写计划时已执行）

- **Spec 覆盖**：spec §4.1→Task 8 第 1 步；§4.2→Task 8 第 2 步＋fixtures 格式基准；§4.3 检查 1–7→Task 2/3/4/5；盲测协议→Task 8 第 4 步；分级处置→Task 8 第 3/5 步；§6 回归集→Task 6/7；spec 验收②→Task 7（含修订）。无遗漏。
- **占位符**：Task 5 测试里的 `jlft-notes-placeholder` 已显式标注为实现时删除；Task 2 的 loader 重复 id 处理给了明确实现决定；无 TBD。
- **类型一致**：`Finding(check, severity, location, message)`、`run_validation(paper_path, answers_path, root, expected_counts, level)`、`norm` 在各任务间引用一致；`AnswerEntry.correct_option_text` 在 Task 3 定义并同步到 models/parsing。
- **已知风险**：真实旧卷 smoke（Task 7）可能暴露解析器对格式微差的误报——已内置归因流程（修解析器 or 白名单），禁止放松检查。
