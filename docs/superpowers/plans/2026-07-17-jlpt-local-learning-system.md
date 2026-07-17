# JLPT 本地学习系统实施计划

> **面向执行代理：** 必须使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans，按任务逐项实现与验证。所有步骤使用复选框跟踪。

**目标：** 建立以本地 Markdown 为中心的 N5–N2 学习系统：保存经检查的学习输出、按固定七天周期复习、记录 JLPT N2 非听力练习，并提供错题分析。

**架构：** 使用 Python 3.10 命令行程序管理 jlpt-notes/ 资料库。卡片采用 JSON 形式的 YAML 兼容前置元数据加 Markdown 正文；复习和答题使用仅追加的 JSONL 日志。Codex 负责检查学习输出与编写原创题目；程序负责校验、持久化、调度、计分与统计。

**技术栈：** Python 3.10 标准库（json、unittest、zipfile）、本地 Git、Codex 定时任务。

## 全局约束

- 长期学习数据必须是本地、可读的 Markdown 和仅追加 JSONL 日志。
- 已确认的语法卡与词汇卡，从确认或实际复习完成日起严格每七天复习一次。
- 答错和“不确定”绝不插入额外复习。
- 不建立听力内容、听力题目或听力统计。
- 题目必须原创；每题保存三个干扰项的错误理由；不得存储或复制官方 JLPT 题目文本。
- 已确认数据的修改必须递增版本并写入面向人的修改记录。
- 每日定时任务只读资料库，不得确认卡片、登记作答或修改复习日期。
- **执行环境修订（2026-07-17）：** 当前环境无法下载 PyYAML 或 pytest，所有测试改用 `python -m unittest`；前置元数据使用 Python 标准库 json 写入，因此仍是 YAML 1.2 可读的 JSON 子集，不依赖外部库。

---

## 目标文件结构

~~~text
AGENTS.md                              # 新聊天遵循的学习系统规则
START-HERE.md                           # 学习者的新聊天启动说明
pyproject.toml                         # 依赖与测试配置
README.md                              # 本地系统使用说明
src/jlpt_notes/__init__.py             # 包版本
src/jlpt_notes/__main__.py             # 命令行入口
src/jlpt_notes/cli.py                  # 命令定义
src/jlpt_notes/models.py               # 卡片、题目、事件模型
src/jlpt_notes/frontmatter.py          # YAML/Markdown 读写
src/jlpt_notes/repository.py           # 路径、草稿、历史、备份
src/jlpt_notes/reviews.py              # 七天复习与每日队列
src/jlpt_notes/n2_taxonomy.py          # N2 非听力题型
src/jlpt_notes/quizzes.py              # 题目保存、计分与反馈
src/jlpt_notes/analytics.py            # 错题统计和报告
tests/test_cli.py
tests/test_frontmatter.py
tests/test_repository.py
tests/test_reviews.py
tests/test_quizzes.py
tests/test_analytics.py
tests/test_backup.py
docs/automation/daily-brief-prompt.md  # 每日简报的持久提示词
jlpt-notes/                            # 实际学习资料库
~~~

### 任务 1：初始化可版本化的 Python 命令行项目

**文件：**

- 新建：pyproject.toml、README.md、AGENTS.md、START-HERE.md
- 新建：src/jlpt_notes/__init__.py、src/jlpt_notes/__main__.py、src/jlpt_notes/cli.py
- 新建：tests/test_cli.py

**接口：**

- 提供 build_parser() -> argparse.ArgumentParser。
- 提供 python -m jlpt_notes --help 与 init 命令。
- 在创建学习数据前初始化本地 Git。

- [ ] **步骤 1：先写失败测试**

~~~python
from jlpt_notes.cli import build_parser

def test_cli_exposes_initialize_command() -> None:
    choices = build_parser()._subparsers._group_actions[0].choices
    assert "init" in choices
~~~

- [ ] **步骤 2：确认测试失败**

运行：python -m pytest tests/test_cli.py::test_cli_exposes_initialize_command -v

预期：因找不到 jlpt_notes 而失败。

- [ ] **步骤 3：实现最小包结构与配置**

~~~toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "jlpt-notes"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["PyYAML>=6.0,<7"]

[project.optional-dependencies]
dev = ["pytest>=8.0,<9"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
~~~

~~~python
# src/jlpt_notes/cli.py
import argparse

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jlpt-notes")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create a learner data repository")
    return parser

def main() -> int:
    build_parser().parse_args()
    return 0
~~~

~~~python
# src/jlpt_notes/__main__.py
from .cli import main
raise SystemExit(main())
~~~

AGENTS.md 固定说明：未来 Codex 聊天先保存学习者原文，再输出检查结果和待确认卡；只有学习者明确说“确认入库”时才写入正式卡。START-HERE.md 给出新聊天的首条操作提示与学习输入模板。

- [ ] **步骤 4：验证**

运行：python -m pytest tests/test_cli.py::test_cli_exposes_initialize_command -v; python -m jlpt_notes --help

预期：测试通过，帮助页显示 init。

- [ ] **步骤 5：建立第一份 Git 历史**

运行：git init; git add pyproject.toml README.md AGENTS.md START-HERE.md src tests; git commit -m "chore: 初始化 JLPT 笔记项目"

预期：工作区干净，存在首个提交。

### 任务 2：实现结构化 Markdown 卡片与资料库校验

**文件：**

- 新建：src/jlpt_notes/models.py、src/jlpt_notes/frontmatter.py、src/jlpt_notes/repository.py
- 新建：tests/test_frontmatter.py

**接口：**

- 提供 Card、read_card(path) -> Card、write_card(path, card) -> None。
- 提供 Repository.init_layout() 与 Repository.validate() -> list[str]。

- [ ] **步骤 1：先写失败测试**

~~~python
from datetime import date
from pathlib import Path
import pytest
from jlpt_notes.models import Card
from jlpt_notes.frontmatter import read_card, write_card

def test_card_round_trips_as_yaml_frontmatter(tmp_path: Path) -> None:
    card = Card(
        id="N3-G-0001", kind="grammar", level="N3", title="～わけではない",
        body="# 核心用法\n并非……", status="confirmed", card_revision=1,
        schema_version=1, created_at=date(2026, 7, 17),
        updated_at=date(2026, 7, 17), next_review=date(2026, 7, 24),
        source={"teacher": "出口仁", "lesson": "12"},
    )
    path = tmp_path / "card.md"
    write_card(path, card)
    assert read_card(path) == card

def test_card_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="level"):
        Card("N9-G-0001", "grammar", "N9", "x", "x", "confirmed", 1, 1,
             date.today(), date.today(), date.today(), {})
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_frontmatter.py -v

预期：因 Card 和读写函数不存在而失败。

- [ ] **步骤 3：实现卡片模型、前置元数据与校验**

~~~python
@dataclass(frozen=True)
class Card:
    id: str
    kind: Literal["grammar", "vocabulary"]
    level: Literal["N5", "N4", "N3", "N2", "N1"]
    title: str
    body: str
    status: Literal["confirmed"]
    card_revision: int
    schema_version: int
    created_at: date
    updated_at: date
    next_review: date
    source: dict[str, str]
    tags: tuple[str, ...] = ()
    confusions: tuple[str, ...] = ()
~~~

使用 yaml.safe_dump(..., allow_unicode=True, sort_keys=False) 写入 --- 分隔的 YAML。校验必填字段、正版本号、N1–N5 等级，以及 ^N[1-5]-(G|V)-\d{4,}$ 格式的 ID。init_layout() 创建 grammar、vocabulary、reading、drafts、reviews、quizzes、analytics、history、schemas、backups。validate() 检查重复 ID、无法解析卡片、修订版缺少 history 记录、失效的易混项引用。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_frontmatter.py -v

预期：通过。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/models.py src/jlpt_notes/frontmatter.py src/jlpt_notes/repository.py tests/test_frontmatter.py; git commit -m "feat: 添加结构化 Markdown 卡片"

预期：卡片格式和校验进入 Git 历史。

### 任务 3：保存学习输出，并以明确确认作为入库门槛

**文件：**

- 修改：src/jlpt_notes/repository.py、src/jlpt_notes/cli.py
- 新建：tests/test_repository.py

**接口：**

- 提供 Repository.create_draft(raw_text, proposed_card) -> Path。
- 提供 Repository.confirm_draft(draft_id, confirmed_on) -> Card。
- 提供 draft-create 与 draft-confirm 命令。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_confirm_draft_preserves_original_and_sets_first_review(repo: Repository) -> None:
    draft_path = repo.create_draft(
        "我的理解：并非全部否定。",
        proposed_card("N3-G-0001", "～わけではない"),
    )
    card = repo.confirm_draft(draft_path.stem, date(2026, 7, 17))
    assert "我的理解：并非全部否定。" in draft_path.read_text(encoding="utf-8")
    assert card.next_review == date(2026, 7, 24)
    assert (repo.root / "grammar" / "n3" / "N3-G-0001.md").exists()
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_repository.py::test_confirm_draft_preserves_original_and_sets_first_review -v

预期：因草稿操作不存在而失败。

- [ ] **步骤 3：实现草稿与确认**

create_draft 在 drafts/<draft_id>.md 写入 draft_id、日期、原始学习输出和“校对后的待确认卡”区段。confirm_draft 必须拒绝重复确认；确认时将 created_at、updated_at、next_review 设为确认日、确认日、确认日加七天；按种类和等级保存正式卡，并向 reviews/events.jsonl 追加 confirmed 事件。draft-confirm 支持 --root、--draft-id 和可选 --date YYYY-MM-DD。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_repository.py -v

预期：通过，且重复确认被拒绝。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/repository.py src/jlpt_notes/cli.py tests/test_repository.py; git commit -m "feat: 添加学习草稿确认流程"

预期：原始学习输出不可被校对结果覆盖。

### 任务 4：实现固定七天复习和带上限的每日队列

**文件：**

- 新建：src/jlpt_notes/reviews.py、tests/test_reviews.py
- 修改：src/jlpt_notes/repository.py、src/jlpt_notes/cli.py

**接口：**

- 提供 due_cards(cards, on_date, limit) -> DailyQueue。
- 提供 complete_review(card, completed_on, result, uncertain) -> Card。
- 提供 today 与 review-complete 命令。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_late_completion_restarts_seven_day_cycle(card: Card) -> None:
    completed = complete_review(card, date(2026, 7, 10), result="incorrect", uncertain=True)
    assert completed.next_review == date(2026, 7, 17)

def test_daily_queue_prioritises_overdue_and_keeps_remainder(cards: list[Card]) -> None:
    queue = due_cards(cards, date(2026, 7, 17), limit=2)
    assert [card.id for card in queue.selected] == ["N2-G-0001", "N3-G-0001"]
    assert queue.not_selected_count == 1
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_reviews.py -v

预期：因调度器不存在而失败。

- [ ] **步骤 3：实现队列和不可覆盖的复习事件**

due_cards 选择 next_review <= on_date 的卡片，按是否逾期、逾期天数降序、错误次数降序、不确定次数降序、到期日、ID 排序。返回选中、到期、逾期、递延数量。complete_review 无论结果如何都将 next_review 设为 completed_on + timedelta(days=7)，并向 reviews/events.jsonl 追加卡片 ID、卡片版本、结果、不确定性、日期。today 接收 --limit 并输出 Markdown 队列；review-complete 仅接受 correct、incorrect、uncertain。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_reviews.py -v

预期：通过。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/reviews.py src/jlpt_notes/repository.py src/jlpt_notes/cli.py tests/test_reviews.py; git commit -m "feat: 添加七天复习队列"

预期：逾期完成后从实际完成日重新开始七天周期。

### 任务 5：保存原创 N2 非听力题目，并解释所有选项

**文件：**

- 新建：src/jlpt_notes/n2_taxonomy.py、src/jlpt_notes/quizzes.py、tests/test_quizzes.py
- 修改：src/jlpt_notes/cli.py

**接口：**

- 提供 N2_NON_LISTENING_TYPES。
- 提供 Question.validate() -> None 与 score(question, selected_option, uncertain) -> QuizResult。
- 提供 quiz-add、quiz-show、quiz-answer 命令。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_scoring_returns_correct_explanation_and_three_distractor_reasons() -> None:
    question = sample_question(correct_option="2")
    result = score(question, selected_option="3", uncertain=True)
    assert result.is_correct is False
    assert result.correct_explanation == "「～わけではない」表示部分否定。"
    assert result.distractor_explanations == {
        "1": "含义变成不可能。", "3": "接续不成立。", "4": "语境的让步关系不成立。"
    }
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_quizzes.py -v

预期：因题型表和计分程序不存在而失败。

- [ ] **步骤 3：实现题型、题目校验、计分和不可覆盖作答日志**

~~~python
N2_NON_LISTENING_TYPES = {
    "vocabulary": (
        "kanji_reading", "orthography", "word_formation",
        "context_expression", "paraphrase", "usage",
    ),
    "grammar": ("grammar_form", "sentence_composition", "text_grammar"),
    "reading": (
        "short_passage", "mid_passage", "long_passage",
        "integrated_comprehension", "thematic_comprehension",
        "information_retrieval",
    ),
}
~~~

题目必须有 1–4 四个选项、一个正确选项、正确项说明和其余三项各自说明；禁止一切听力题型。原创题目保存到 quizzes/questions/<question_id>.md。作答向 quizzes/attempts.jsonl 追加题目 ID/版本、所选项、结果、不确定性、题型、能力标签、错因标签与时间。quiz-show 不显示答案；quiz-answer 必须输出正确解释和三个干扰项解释。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_quizzes.py -v

预期：通过。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/n2_taxonomy.py src/jlpt_notes/quizzes.py src/jlpt_notes/cli.py tests/test_quizzes.py; git commit -m "feat: 添加 N2 非听力测验记录"

预期：每道四选一题在保存后仍可解释所有选项。

### 任务 6：将词汇错误保存为候选卡，而非自动加入复习

**文件：**

- 修改：src/jlpt_notes/quizzes.py、src/jlpt_notes/repository.py、src/jlpt_notes/cli.py、tests/test_quizzes.py

**接口：**

- 提供 Repository.create_vocab_candidate(attempt, question) -> Path。
- 提供 vocab-candidates 与 vocab-confirm 命令。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_wrong_vocabulary_answer_creates_candidate_but_not_review_card(repo: Repository) -> None:
    candidate = repo.create_vocab_candidate(wrong_vocabulary_attempt("N2-Q-0001"), vocabulary_question())
    assert candidate.exists()
    assert not list((repo.root / "vocabulary" / "n2").glob("*.md"))
    assert "错误选项" in candidate.read_text(encoding="utf-8")
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_quizzes.py::test_wrong_vocabulary_answer_creates_candidate_but_not_review_card -v

预期：因候选卡写入尚未实现而失败。

- [ ] **步骤 3：实现候选卡与明确提升**

词汇题答错时，在 drafts/vocabulary-candidates/<candidate_id>.md 保存词形、读音、正确释义、题目语境、学习者选项、正确选项、选项解释、能力标签和来源题目 ID，但不得创建正式词汇卡。vocab-candidates 列出未处理候选卡。vocab-confirm --candidate-id 将一张候选卡转为普通词汇草稿，再经过任务 3 的确认流程，确认后才启动七天复习。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_quizzes.py tests/test_repository.py -v

预期：通过。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/quizzes.py src/jlpt_notes/repository.py src/jlpt_notes/cli.py tests/test_quizzes.py; git commit -m "feat: 添加可确认的词汇候选卡"

预期：词汇错误可沉淀，但不会悄悄增加复习负担。

### 任务 7：汇总错题并生成日报、周报

**文件：**

- 新建：src/jlpt_notes/analytics.py、tests/test_analytics.py
- 修改：src/jlpt_notes/cli.py

**接口：**

- 提供 aggregate_attempts(attempts) -> AnalyticsSummary。
- 提供 render_weekly_report(summary) -> str。
- 提供 report-daily 与 report-weekly 命令。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_analytics_groups_by_item_type_and_error_reason() -> None:
    summary = aggregate_attempts([
        attempt(item_type="grammar_form", error_tags=("conjugation",)),
        attempt(item_type="grammar_form", error_tags=("meaning_nuance",)),
        attempt(item_type="information_retrieval", error_tags=("detail_location",)),
    ])
    assert summary.by_item_type["grammar_form"].incorrect == 2
    assert summary.by_error_tag["detail_location"] == 1
    assert "grammar_form" in render_weekly_report(summary)
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_analytics.py -v

预期：因汇总函数尚未实现而失败。

- [ ] **步骤 3：实现校验后的统计和报告**

允许的错因标签只有：reading、orthography、word_formation、meaning_confusion、usage、conjugation、meaning_nuance、context_connection、sentence_structure、main_idea、detail_location、information_retrieval、careless、uncertain。按题型、错因、等级、关联卡片汇总正确、错误与不确定次数。report-daily 合并复习队列、三个最薄弱类型/错因和未处理候选卡数量，但不写入学习数据。report-weekly --since YYYY-MM-DD 与之前的作答数据比较。

- [ ] **步骤 4：验证通过**

运行：python -m pytest tests/test_analytics.py -v

预期：通过。

- [ ] **步骤 5：提交**

运行：git add src/jlpt_notes/analytics.py src/jlpt_notes/cli.py tests/test_analytics.py; git commit -m "feat: 添加 JLPT 错题统计"

预期：题型与错因被明确区分。

### 任务 8：加入安全的每日简报、备份与新聊天交接

**文件：**

- 新建：docs/automation/daily-brief-prompt.md、tests/test_backup.py
- 修改：src/jlpt_notes/repository.py、src/jlpt_notes/cli.py、README.md、AGENTS.md、START-HERE.md

**接口：**

- 提供 Repository.create_backup(on_date) -> Path。
- 提供 validate、backup、report-daily 命令。
- 建立一个只读的 Codex 本地每日定时任务。

- [ ] **步骤 1：先写失败测试**

~~~python
def test_backup_is_zip_and_excludes_git_directory(repo: Repository) -> None:
    archive = repo.create_backup(date(2026, 7, 17))
    with ZipFile(archive) as backup:
        assert "grammar/n2/N2-G-0001.md" in backup.namelist()
        assert not any(name.startswith(".git/") for name in backup.namelist())
~~~

- [ ] **步骤 2：确认失败**

运行：python -m pytest tests/test_backup.py -v

预期：因备份功能不存在而失败。

- [ ] **步骤 3：实现备份、交接文档和持久提示词**

create_backup 以原子方式写入 backups/YYYY-MM-DD-jlpt-notes.zip，排除 .git、backups 和 Python 缓存目录。validate 打印所有格式/引用错误，发现错误时返回退出码 1。每日简报提示词只允许运行 report-daily 和 validate，禁止确认卡片、提交答案、改动复习日期或创建备份。AGENTS.md 与 START-HERE.md 明确说明：新聊天读取这两份文件和 jlpt-notes/README.md 后，即可接收学习输出、检查并生成待确认卡；学习者仍需在聊天中明确确认入库。

- [ ] **步骤 4：完整验证**

运行：python -m pytest -v; python -m jlpt_notes init --root jlpt-notes; python -m jlpt_notes validate --root jlpt-notes; python -m jlpt_notes report-daily --root jlpt-notes --limit 15

预期：全部测试通过；新资料库校验通过；日报显示零到期卡而不报错。

- [ ] **步骤 5：创建定时任务并提交**

使用 codex_app__automation_update 创建名为“JLPT 每日复习简报”的本地定时任务，使用 docs/automation/daily-brief-prompt.md 的内容和普通通知策略。先手动测试一次，再启用每日周期。随后运行：git add docs/automation README.md AGENTS.md START-HERE.md src/jlpt_notes/repository.py src/jlpt_notes/cli.py tests/test_backup.py; git commit -m "feat: 添加每日简报、备份和聊天交接"

预期：定时任务保持只读；新聊天可以按项目说明继续使用资料库；学习数据可从本地历史或备份恢复。

## 计划自查

- 结构化 Markdown、原始学习输出、确认入库、卡片与结构版本：任务 2–3。
- 固定七天、逾期完成、每日上限、温和滚动：任务 4。
- N2 词汇、语法、阅读题型；无听力；四个选项的完整解释：任务 5。
- 不预先录入词汇也可测试，错误词只创建候选卡：任务 6。
- 错题分析、日报、周报、未来出题侧重：任务 7。
- 本地 Git、校验、备份、只读定时任务及新聊天交接：任务 1、2、8。

所有持久化操作由 Repository 管理；所有复习更新通过 complete_review；N2 题型只在 N2_NON_LISTENING_TYPES 定义一次；统计前校验错因标签。模型生成的教学内容与本地保存逻辑分离，使 Markdown 资料库始终是长期可迁移的唯一事实来源。
