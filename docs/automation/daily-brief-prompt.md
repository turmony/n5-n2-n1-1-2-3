# JLPT 每日复习简报

在项目目录中运行：

```powershell
$env:PYTHONPATH='src'; python -m jlpt_notes report-daily --root jlpt-notes --limit 15; python -m jlpt_notes validate --root jlpt-notes
```

只报告结果。不得确认入库、提交答题、改动复习日期、生成题目或创建备份。
