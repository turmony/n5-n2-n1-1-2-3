# N5 全语法综合诊断卷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一套以现有 118 张已确认 N5 语法卡为知识范围的 60 分钟、45 题原创综合诊断卷，并保留可逐题评分和解释四个选项的数据。

**Architecture:** 每道题作为独立 Markdown 题目文件保存，完整记录四个选项、唯一答案及干扰项解释；另生成一份只含题目、不泄露答案的学习者试卷。三类题型分别完成后，再统一进行结构校验、答案分布检查、覆盖检查和人工语言复核。

**Tech Stack:** Markdown、JSON-compatible YAML frontmatter、现有 `jlpt_notes.quizzes.Question` 数据模型与 `jlpt_notes.repository.Repository` 存储约定。

## Global Constraints

- 恰好 45 道四选一题，建议用时合计 60 分钟。
- 题型分布为 28 道 `grammar_form`、10 道 `sentence_composition`、7 道 `text_grammar`。
- 不含听力；题目文字全部原创。
- 知识范围只取自现有 118 张已确认 N5 语法卡，不虚构缺失的 `N5-G-0072`。
- 每题只有一个在语法和语境上都成立的最佳答案。
- 每题都保存正确项解释和其余三个选项的独立错误解释。
- 首次交付的学习者试卷不显示答案或解析。
- 测试不修改正式卡片、复习事件或复习日期。

---

### Task 1: 建立语法覆盖矩阵并编写 28 道语法形式选择题

**Files:**
- Read: `jlpt-notes/grammar/n5/N5-G-0001.md` through `jlpt-notes/grammar/n5/N5-G-0119.md`, excluding the absent `N5-G-0072.md`
- Create: `jlpt-notes/quizzes/questions/N5-Q-0001.md` through `jlpt-notes/quizzes/questions/N5-Q-0028.md`

**Interfaces:**
- Consumes: 正式卡片前置元数据与正文中的核心用法、接续、易混项和例句。
- Produces: 28 个符合 `Question` 字段约束的 `grammar_form` 题目文件，供最终试卷汇编和评分使用。

- [ ] **Step 1: 读取全部正式卡片并划分覆盖簇**

将卡片归入活用与时态、格助词、提示与并列助词、存在与移动、数量与限定、授受、原因与目的、动作顺序、普通形接续、自动词与他动词、语气与篇章衔接等覆盖簇。保证每个覆盖簇至少成为一道题的主要或次要考点。

- [ ] **Step 2: 编写 N5-Q-0001 至 N5-Q-0028**

每个文件使用以下完整结构，且 `item_type` 固定为 `grammar_form`：

```markdown
---
{
  "id": "N5-Q-0001",
  "revision": 1,
  "level": "N5",
  "item_type": "grammar_form",
  "prompt": "原创题干",
  "options": {"1": "选项一", "2": "选项二", "3": "选项三", "4": "选项四"},
  "correct_option": "唯一正确选项编号",
  "correct_explanation": "说明语义、接续和语境为何成立，并标明相关语法卡。",
  "option_explanations": {
    "错误选项编号": "该项的独立错误原因",
    "错误选项编号": "该项的独立错误原因",
    "错误选项编号": "该项的独立错误原因"
  }
}
---

原创题干
```

- [ ] **Step 3: 校验第一部分的文件结构**

运行：

```powershell
$env:PYTHONPATH='src'; python -c "import json,pathlib; from jlpt_notes.quizzes import Question; fs=sorted(pathlib.Path('jlpt-notes/quizzes/questions').glob('N5-Q-00[0-2][0-9].md')); assert len(fs)==28; [Question(**json.loads(p.read_text(encoding='utf-8')[4:].split('\n---\n\n',1)[0])) for p in fs]; print('28 grammar_form questions valid')"
```

预期：输出 `28 grammar_form questions valid`，没有异常。

- [ ] **Step 4: 复核语法形式题质量**

逐题确认：只有一个最佳答案；三个干扰项分别对应接续、语义边界或助词功能错误；题干不依赖 N5 范围外的冷僻词汇；正确项编号分布没有连续规律。

### Task 2: 编写 10 道句子重组题

**Files:**
- Create: `jlpt-notes/quizzes/questions/N5-Q-0029.md` through `jlpt-notes/quizzes/questions/N5-Q-0038.md`

**Interfaces:**
- Consumes: Task 1 的覆盖矩阵，优先选取尚未深度考查的普通形接续、修饰结构、动作顺序、授受和复合助词功能。
- Produces: 10 个 `sentence_composition` 题目文件，题干明确给出四个语块和需要选择的指定位置。

- [ ] **Step 1: 设计十个唯一可重排的完整句子**

每题先确定自然完整句，再切分为四个语块。检查语块之间的助词、活用和修饰关系，确保只有一种符合题意的排序。

- [ ] **Step 2: 编写 N5-Q-0029 至 N5-Q-0038**

沿用 Task 1 的完整 frontmatter 结构，将 `item_type` 改为 `sentence_composition`。`prompt` 必须说明“将四个语块排列成自然的句子，★处应填哪一项”，四个选项就是四个待排列语块；`correct_option` 是排入 ★ 位置的语块编号。解释中写出完整正确语序，并逐项说明其他语块为何不在 ★ 位置。

- [ ] **Step 3: 校验第二部分的结构和唯一排序**

运行：

```powershell
$env:PYTHONPATH='src'; python -c "import json,pathlib; from jlpt_notes.quizzes import Question; fs=sorted(pathlib.Path('jlpt-notes/quizzes/questions').glob('N5-Q-00*.md'))[28:38]; assert len(fs)==10; qs=[Question(**json.loads(p.read_text(encoding='utf-8')[4:].split('\n---\n\n',1)[0])) for p in fs]; assert all(q.item_type=='sentence_composition' for q in qs); print('10 sentence_composition questions valid')"
```

预期：输出 `10 sentence_composition questions valid`。

### Task 3: 编写 7 道篇章语法题

**Files:**
- Create: `jlpt-notes/quizzes/questions/N5-Q-0039.md` through `jlpt-notes/quizzes/questions/N5-Q-0045.md`

**Interfaces:**
- Consumes: Task 1 的覆盖矩阵和前 38 题未充分覆盖的时间顺序、原因、对比、指示、句末语气及上下文衔接。
- Produces: 7 个 `text_grammar` 题目文件；每题的短篇语境足以排除三个干扰项。

- [ ] **Step 1: 编写两至三个连续的原创短篇语境**

每个短篇围绕日常生活、学习、出行或安排展开。七个空格分别考查句内语法与句际逻辑，不能靠单句形式匹配直接猜出答案。

- [ ] **Step 2: 编写 N5-Q-0039 至 N5-Q-0045**

沿用 Task 1 的完整 frontmatter 结构，将 `item_type` 改为 `text_grammar`。同一短篇的共享文字应完整放入各题 `prompt`，并清楚标示当前作答空格。每个解释必须引用上下文线索。

- [ ] **Step 3: 校验第三部分的结构与篇章依赖**

运行：

```powershell
$env:PYTHONPATH='src'; python -c "import json,pathlib; from jlpt_notes.quizzes import Question; fs=sorted(pathlib.Path('jlpt-notes/quizzes/questions').glob('N5-Q-00*.md'))[38:45]; assert len(fs)==7; qs=[Question(**json.loads(p.read_text(encoding='utf-8')[4:].split('\n---\n\n',1)[0])) for p in fs]; assert all(q.item_type=='text_grammar' for q in qs); print('7 text_grammar questions valid')"
```

预期：输出 `7 text_grammar questions valid`。

### Task 4: 汇编无答案试卷并进行整卷验收

**Files:**
- Create: `jlpt-notes/quizzes/papers/2026-07-26-n5-comprehensive-test.md`
- Read: `jlpt-notes/quizzes/questions/N5-Q-0001.md` through `jlpt-notes/quizzes/questions/N5-Q-0045.md`

**Interfaces:**
- Consumes: 三部分共 45 个已校验题目文件。
- Produces: 可直接交给学习者作答、没有答案和解析的完整试卷。

- [ ] **Step 1: 汇编试卷头部与作答说明**

写明总题数 45、建议时间 60 分钟、三部分时间分配，以及答案格式 `1-2, 2-4, 3-1?`；说明 `?` 表示不确定。

- [ ] **Step 2: 按题号汇编三部分题目**

第一部分放入 1–28 题，第二部分放入 29–38 题，第三部分放入 39–45 题。只复制 `prompt` 和四个选项，不复制 `correct_option`、`correct_explanation` 或 `option_explanations`。

- [ ] **Step 3: 运行整卷结构验收**

运行：

```powershell
$env:PYTHONPATH='src'; python -c "import json,pathlib,collections; from jlpt_notes.quizzes import Question; fs=sorted(pathlib.Path('jlpt-notes/quizzes/questions').glob('N5-Q-00*.md')); assert len(fs)==45; qs=[Question(**json.loads(p.read_text(encoding='utf-8')[4:].split('\n---\n\n',1)[0])) for p in fs]; assert collections.Counter(q.item_type for q in qs)=={'grammar_form':28,'sentence_composition':10,'text_grammar':7}; assert all(set(q.options)=={'1','2','3','4'} and len(q.option_explanations)==3 for q in qs); print('45-question paper structurally valid')"
```

预期：输出 `45-question paper structurally valid`。

- [ ] **Step 4: 运行答案分布与泄露检查**

统计四个正确选项的出现次数，确保每个编号出现 10–12 次且没有五题连续为同一编号；搜索学习者试卷，确保未出现 `correct_option`、`correct_explanation`、`option_explanations` 或“答案：”。

- [ ] **Step 5: 人工完成最终语言与覆盖复核**

从头通读试卷和答案数据，检查日语自然度、题干指代、标点、唯一答案、短文一致性及从易到难的梯度；对照 11 个覆盖簇，确认每簇都有直接考查，并确认没有听力要求。

- [ ] **Step 6: 提交题库与试卷**

```powershell
git add -- 'jlpt-notes/quizzes/questions' 'jlpt-notes/quizzes/papers/2026-07-26-n5-comprehensive-test.md'
git commit -m "feat: 添加 N5 全语法综合诊断卷"
```
