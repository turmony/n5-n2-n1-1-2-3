---
name: quiz-generate
description: 当用户说“出题”“出卷”“出新卷”“生成试卷”或指定语法练习时使用。只从日本語NET检索并核实原题或教学例句，优先复用本地题源缓存，以结构化清单生成 JLPT N5–N1 非听力练习；不用于判分。
---

# JLPT 日本語NET 题源组卷

题目必须建立在实际打开并核实的日本語NET（`nihongokyoshi-net.com`）内容上。允许完整保留的“网站原题”和根据教学例句制作的“例句派生题”；不得无来源自由编题，不得把派生题称为网站原题、官方题或历年真题。

## 不可降低的质量要求

- 网站原题必须同时核实题目和来源答案，保留题干、上下文、空格位置、全部选项及顺序；缺答案、多解或来源冲突时弃用。
- 例句派生题必须来自直接讲解目标语法的页面，保留原例句并逐项记录改动、答案依据和四个干扰项依据。题干必须锁定唯一答案；最多两轮修订后仍有多解则弃用。
- 每道四选一题解释全部四项。中文翻译与 AI 解析不能反向改变来源内容。
- 题源不足、页面不可访问或日本語NET没有相应材料时，如实报告缺口；不得改用其他网站，也不得擅自缩减题量或扩大考点。

## 第 0 步：读取与定量

先读仓库 `START-HERE.md`、`README.md`、`AGENTS.md`、资料库 `jlpt-notes/README.md` 与目标卡片前置元数据，再读目标卡的接续、语义边界和易混项。

用户未指定题量时：

- 指定了卡片或课程范围：每张目标卡默认 1 题，最多 20 题；
- 未指定范围、按到期或薄弱卡选题：默认 20 题；
- 默认全部为形式选择题。排序、完形或超过 20 题只在用户明确要求时加入。

用户指定了语法或卡片时直接执行；未指定时先给出选卡建议并等待确认。指定练习不改变七天复习日期。

## 第 1 步：缓存优先的检索与取证

1. 先用 `source_cache.py lookup` 按网址或语法卡查找 90 天内的缓存。缓存命中且 `verify` 通过时直接复用，保留证据原访问日期，不伪造本次访问。
2. 缓存未命中时，只搜索日本語NET。先用一次批量搜索发现目标页面，再并行抓取已选页面（并发上限 4）；一旦题量和卡片覆盖满足即停止。搜索摘要只用于发现页面，不能作为证据。
3. 优先完整原题；不足时使用直接教学页面的自然例句派生。运营者背景使用缓存中的同一份已核实记录，不重复抓取。
4. 只保存最终采用页面中足以复核题目、答案或例句的原始摘录／截图。不得保存搜索结果 JSON、未采用候选的整页抓取或“为了证明搜索过”而保存的入口页。
5. 用下列命令把选中证据加入缓存；命令拒绝非日本語NET网址、搜索 JSON 和空证据：

```text
uv run python .claude/skills/quiz-generate/scripts/source_cache.py add --root jlpt-notes --url <URL> --title <标题> --publisher <运营者> --accessed-at <YYYY-MM-DD> --grammar <卡号> --locator <定位> --evidence <摘录文件>
uv run python .claude/skills/quiz-generate/scripts/source_cache.py verify --root jlpt-notes
```

## 第 2 步：单一结构化清单与预检

试卷的唯一手工编辑源是一个 JSON draft。先用 `quiz_pipeline.py template` 建立清单，再填题；不要分别手写试卷、答案和题卡。字段契约可由 `template` 输出查看，脚本的 `validate` 是结构与状态门禁。

```text
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py template --output <draft.json>
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py validate --root . --draft <draft.json> --stage preflight
```

每题在进入盲审前必须记录并通过三项预检：表面接续、语义排他性、唯一解理由。预检不能证明语法正确，但应在生成三件套前淘汰明显多解、虚构形式、纯词性错误凑数和来源字段不完整的题。

用 `phase start/end` 记录 `selection`、`search`、`scrape`、`draft`、`preflight`、`blind_review`、`revision`、`render`、`validation` 的时间及调用数；交付时报告各阶段用时。计时只记录实际完成的阶段。

## 第 3 步：预览与独立审题

预检通过后，渲染到临时目录供盲审，不写正式试卷路径：

```text
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py render --root . --draft <draft.json> --preview-dir <临时目录>
```

派独立子代理完成首次全卷盲答。第一阶段只提供预览试卷和目标语法卡目录，禁止读取答案、题卡、来源和生成记录；要求逐题给出答案、理由、信心，并指出多解或不自然之处。第二阶段再按题源类型提供对应的最小证据摘录与该题生成记录，核对来源和唯一解。

审题结果按题写回 draft，`reviewed_revision` 必须等于该题 `revision`。若修改题目，用 `revise` 增加该题 revision 并只清空该题审题状态；随后由独立审题者重新盲审该题。未修改题不重跑全卷盲答。跨题重复与结构一致性仍在最终机械校验中全卷检查。

```text
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py revise --draft <draft.json> --question-id <ID> --reason <原因>
```

## 第 4 步：最终生成与校验

所有题的预检、盲审和来源复核均通过且审题版本匹配后，才执行最终渲染。脚本从同一 draft 生成试卷、答案、题卡，并在 `quizzes/sources/<试卷名>/manifest.json` 保存最终清单。

```text
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py validate --root . --draft <draft.json> --stage final
uv run python .claude/skills/quiz-generate/scripts/quiz_pipeline.py render --root . --draft <draft.json> --final
uv run python .claude/skills/quiz-generate/scripts/validate_quiz.py --paper <试卷路径> --answers <答案路径> --structure <形式,排序,完形> --level <N5|N4|N3|N2|N1>
uv run python -m jlpt_notes validate-links --root jlpt-notes
```

网站原题有问题只能替换，不能改写后继续标为原题。派生题每次修订都写入 `transformations` 并重新盲审该题；两轮仍有问题则弃用。机械校验不能替代来源真实性、唯一解或语法判断。

## 第 5 步：交付

说明试卷、答案、题卡、manifest 和缓存证据路径；报告题量、等级、各卡覆盖、原题／派生题数量、缓存命中／新抓取数量、各阶段用时、来源核对、机械校验及独立审题结果。未执行的步骤必须如实标注。

仅在数量、题型、范围和全部检查均满足后提交本地 Git。正式卡、复习日期和确认事件不得修改。

## 维护

用户只要求修改 skill 时，不执行联网组卷或创建试卷。修改流程、结构化清单或缓存能力时，同步更新脚本与有意义的回归测试；不得声称脚本能自动证明语法正确或唯一解。
