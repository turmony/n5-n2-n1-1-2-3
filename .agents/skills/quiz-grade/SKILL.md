---
name: quiz-grade
description: 判定学习者的 JLPT 试卷作答并生成成绩报告。当用户说“判分”“判卷”“成绩”“作答完了”或“对答案”等时使用；不用于生成新卷。
---

# JLPT 判分

这是 Codex 的仓库级入口。执行前先阅读仓库根目录的 `START-HERE.md`、`README.md`、`AGENTS.md`，然后完整阅读并严格执行唯一的流程源文件：

`../../../.claude/skills/quiz-grade/SKILL.md`

在生成报告前，按源流程读取 `../../../.claude/skills/quiz-grade/references/result-template.md`。不要复制、简化或绕过其中的判分规则、报告结构、追加记录和提交规则。`.claude/skills/quiz-grade/` 是本 skill 的单一维护来源。
