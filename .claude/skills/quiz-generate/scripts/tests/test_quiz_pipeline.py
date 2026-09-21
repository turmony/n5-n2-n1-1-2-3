import json
import subprocess
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "quiz_pipeline.py"
VALIDATOR = Path(__file__).resolve().parents[1] / "validate_quiz.py"


def run_script(script, *args):
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", check=False)


def make_question(number=1, qid="N4-Q-0007"):
    return {
        "number": number,
        "id": qid,
        "revision": 1,
        "section": "form",
        "item_type": "form_choice",
        "prompt": "雨が降った（　）、試合は続けられた。",
        "translation": "尽管下雨，比赛还是继续了。",
        "tested_cards": ["N4-G-0001"],
        "conjugation": "普通形＋のに",
        "options": {"1": "のに", "2": "ので", "3": "まで", "4": "から"},
        "correct_option": "1",
        "correct_explanation": "逆接关系只能选のに。",
        "option_explanations": {
            "1": "正确，表达逆接。", "2": "表示原因。",
            "3": "表示终点。", "4": "表示原因。",
        },
        "source": {
            "kind": "derived_from_example",
            "site_name": "日本語NET",
            "publisher": "日本語NET／ノッチ",
            "title": "〜のに",
            "url": "https://nihongokyoshi-net.com/example/",
            "locator": "例文区",
            "accessed_at": "2026-09-21",
            "evidence_paths": ["quizzes/sources/cache/evidence.md"],
            "original_example": "雨が降ったのに、試合は続けられた。",
            "transformations": ["挖空のに。"],
            "answer_basis": "来源讲解说明逆接。",
            "distractor_basis": ["1. 逆接", "2. 原因", "3. 终点", "4. 原因"],
        },
        "preflight": {
            "status": "passed",
            "surface_connection": "四项均为真实形式。",
            "semantic_exclusion": "后句与前句构成逆接。",
            "unique_answer_rationale": "只有のに同时满足接续和语义。",
        },
        "review": {
            "blind": {
                "status": "passed", "reviewed_revision": 1,
                "reviewer": "blind-agent", "reviewed_at": "2026-09-21T10:00:00+08:00",
                "answer": "1", "notes": "高信心，未发现多解。",
            },
            "source": {
                "status": "passed", "reviewed_revision": 1,
                "reviewer": "blind-agent", "reviewed_at": "2026-09-21T10:01:00+08:00",
                "notes": "原例句存在，改动最小。",
            },
        },
    }


def make_draft():
    return {
        "schema_version": 1,
        "quiz": {
            "slug": "2026-09-21-n4-pipeline-test-1",
            "title": "N4 流水线测试卷",
            "date": "2026-09-21",
            "level": "N4",
            "suggested_minutes": 1,
        },
        "questions": [make_question()],
        "workflow": {"phases": [], "revision_history": []},
    }


def test_final_render_produces_validator_compatible_artifacts(env_basic, tmp_path):
    evidence = env_basic / "jlpt-notes/quizzes/sources/cache/evidence.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("日本語NETの原例文：雨が降ったのに、試合は続けられた。\n", encoding="utf-8")
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(make_draft(), ensure_ascii=False, indent=2), encoding="utf-8")

    checked = run_script(PIPELINE, "validate", "--root", env_basic, "--draft", draft, "--stage", "final")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    rendered = run_script(PIPELINE, "render", "--root", env_basic, "--draft", draft, "--final")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    paths = json.loads(rendered.stdout)

    validated = run_script(
        VALIDATOR, "--paper", paths["paper"], "--answers", paths["answers"],
        "--root", env_basic, "--structure", "1,0,0", "--level", "N4",
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
    assert manifest["workflow"]["phases"][-1]["name"] == "render"


def test_final_requires_current_review_and_revise_resets_only_target(tmp_path):
    root = tmp_path / "repo"
    evidence = root / "jlpt-notes/quizzes/sources/cache/evidence.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("evidence", encoding="utf-8")
    data = make_draft()
    second = make_question(2, "N4-Q-0008")
    second["prompt"] = "雪が降った（　）、電車は動いた。"
    data["questions"].append(second)
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    revised = run_script(
        PIPELINE, "revise", "--draft", draft,
        "--question-id", "N4-Q-0007", "--reason", "干扰项可能多解",
    )
    assert revised.returncode == 0, revised.stdout + revised.stderr
    changed = json.loads(draft.read_text(encoding="utf-8"))
    assert changed["questions"][0]["revision"] == 2
    assert changed["questions"][0]["review"]["blind"]["status"] == "pending"
    assert changed["questions"][1]["review"]["blind"]["status"] == "passed"

    final = run_script(PIPELINE, "validate", "--root", root, "--draft", draft, "--stage", "final")
    assert final.returncode == 1
    assert "preflight.status" in final.stdout
    assert "N4-Q-0008" not in "\n".join(json.loads(final.stdout)["errors"])


def test_phase_records_duration_and_metrics(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(make_draft(), ensure_ascii=False, indent=2), encoding="utf-8")
    started = run_script(PIPELINE, "phase", "--draft", draft, "--name", "search", "--action", "start")
    assert started.returncode == 0
    ended = run_script(
        PIPELINE, "phase", "--draft", draft, "--name", "search", "--action", "end",
        "--metric", "calls=1", "--metric", "cache_hits=3",
    )
    assert ended.returncode == 0, ended.stdout + ended.stderr
    record = json.loads(ended.stdout)
    assert record["metrics"] == {"calls": 1, "cache_hits": 3}
    assert record["duration_seconds"] >= 0
