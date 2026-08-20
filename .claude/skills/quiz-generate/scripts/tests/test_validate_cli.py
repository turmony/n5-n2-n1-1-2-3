import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate_quiz.py"
PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"
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
