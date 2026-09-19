---
name: quiz-generate
description: 当用户说“出题”“出卷”“出新卷”“生成试卷”或指定语法卡练习时使用。从日本日语教学网站检索已有练习题组卷，禁止 AI 自编题；不用于判分。
---

# JLPT 网上练习题组卷

这是 Codex 的仓库级入口。执行前先阅读仓库根目录的 `START-HERE.md`、`README.md`、`AGENTS.md`，然后完整阅读并严格执行唯一的流程源文件：

`../../../.claude/skills/quiz-generate/SKILL.md`

`.claude/skills/quiz-generate/` 是本 skill 的单一维护来源。遵守其中的日本网站题源、禁止自编或改造成题、来源证据、题量不足处理、校验和独立审题规则；不要另写一套简化流程。普通教学练习题即可，不要求历年真题。
