"""历史事故回归：每个真实坑一类，mutate 重现后必须被拦截。"""
from quizlib.models import ERROR

NEW_PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"
NEW_ANSWERS = "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md"
CARD5 = "jlpt-notes/quizzes/questions/N4-Q-0005.md"
CARD4 = "jlpt-notes/quizzes/questions/N4-Q-0004.md"
CARD3 = "jlpt-notes/quizzes/questions/N4-Q-0003.md"
ORDER_STEM = "去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。"


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
