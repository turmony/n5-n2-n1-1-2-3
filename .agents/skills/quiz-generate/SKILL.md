---
name: quiz-generate
description: 当用户说“出题”“出卷”“出新卷”“生成试卷”或指定语法练习时使用。只从日本語NET检索并核实原题或教学例句，优先复用本地题源缓存，以结构化清单生成 JLPT N5–N1 非听力练习；不用于判分。
---

# JLPT 网上练习题组卷

这是 Codex 的仓库级入口。执行前先阅读仓库根目录的 `START-HERE.md`、`README.md`、`AGENTS.md`，然后完整阅读并严格执行唯一的流程源文件：

`../../../.claude/skills/quiz-generate/SKILL.md`

`.claude/skills/quiz-generate/` 是本 skill 的单一维护来源。遵守其中的网站原题／例句派生题双轨规则、日本語NET 单站点限制、缓存与最小证据规则、结构化清单、唯一解预检、增量独立审题、计时和最终校验要求；不要另写一套简化流程。普通教学材料即可，不要求历年真题。
