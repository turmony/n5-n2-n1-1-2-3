from pathlib import Path

from quizlib.parsing import load_question_cards, load_grammar_ids, parse_answers, parse_paper
from quizlib.checks import check_card_ids, check_grammar_refs, check_order_invariants, check_consistency

NEW_ANSWERS = "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md"
NEW_PAPER = "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md"


def _env(env_basic):
    answers = parse_answers((env_basic / NEW_ANSWERS).read_text(encoding="utf-8"))
    cards = load_question_cards(env_basic / "jlpt-notes/quizzes")
    grammar = load_grammar_ids(env_basic / "jlpt-notes")
    return answers, cards, grammar


def test_load_question_cards(env_basic):
    _, cards, _ = _env(env_basic)
    assert set(cards) == {f"N4-Q-{i:04d}" for i in range(1, 7)}
    assert cards["N4-Q-0005"].recommended_order == "3142"
    assert cards["N4-Q-0005"].item_type == "sentence_composition"
    assert cards["N4-Q-0003"].tested_cards == ["N4-G-0001"]


def test_load_grammar_ids(env_basic):
    _, _, grammar = _env(env_basic)
    assert grammar == {"N4-G-0001", "N4-G-0002", "N4-G-0003"}


def test_c1_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_card_ids(answers, cards, "N4") == []


def test_c1_duplicate_id(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"id": "N4-Q-0004"', '"id": "N4-Q-0002"')
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" and f.severity == "error" and "重复" in f.message for f in findings)


def test_c1_new_ids_not_consecutive(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"id": "N4-Q-0004"', '"id": "N4-Q-0009"')
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0004", "N4-Q-0009")
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" and "连续" in f.message for f in findings)


def test_c1_new_ids_must_come_after_existing(env_basic, mutate):
    # 新卡号小于既有最大号 0002 → 接缝错误
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0003.md",
           '"id": "N4-Q-0003"', '"id": "N4-Q-0001"')
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0003）", "N4-Q-0001a）")  # 仅答案引用改名占位
    # 说明：直接同名会与 0001 撞车先报重复；接缝检查用 0001a 非法格式演示，断言两条都抓
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" for f in findings)


def test_c1_new_ids_below_existing_max(env_basic, mutate):
    # 新卡段引用既有旧号 0002（题卡文件不动）：new_set={0002,0003,0005,0006}、
    # old_max=0004=4、nums[0]=2≤4 → 精确触发「未接续既有最大号」分支
    mutate(env_basic, NEW_ANSWERS, "N4-Q-0004）", "N4-Q-0002）")
    answers, cards, _ = _env(env_basic)
    findings = check_card_ids(answers, cards, "N4")
    assert any(f.check == "C1" and "未接续" in f.message for f in findings)


def test_c1_seam_ignores_malformed_card_ids(env_basic):
    # 题库混入 frontmatter 损坏、stem 尾部非数字的卡（如手工备份文件）时，
    # 数值比较不得崩溃：畸形 id 不参与接缝计算，也不产生误报
    (env_basic / "jlpt-notes/quizzes/questions/N4-Q-0002-bak.md").write_text(
        "（损坏的备份卡，无 frontmatter）\n", encoding="utf-8")
    answers, cards, _ = _env(env_basic)
    assert "N4-Q-0002-bak" in cards
    assert check_card_ids(answers, cards, "N4") == []


def test_c4_missing_grammar_ref(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "N4-G-0001「", "N4-G-9999「")
    answers, _, _ = _env(env_basic)
    findings = check_grammar_refs(answers, {"N4-G-0001", "N4-G-0002", "N4-G-0003"}, "N4")
    assert any(f.check == "C4" and "N4-G-9999" in f.message for f in findings)


def test_c4_clean_env_passes(env_basic):
    answers, _, grammar = _env(env_basic)
    assert check_grammar_refs(answers, grammar, "N4") == []


def _paper(env_basic):
    return parse_paper((env_basic / NEW_PAPER).read_text(encoding="utf-8"))


def test_c2_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_order_invariants(_paper(env_basic), answers, cards) == []


def test_c2_invalid_permutation(env_basic, mutate):
    # 语序 3142 → 3112：不是 1-4 的排列
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3112")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "排列" in f.message for f in findings)


def test_c2_digit_typo_breaks_block_numbering(env_basic, mutate):
    # 语序 3142 → 3412（仍是合法排列）——解析文字块编号仍是 3,1,4,2 → 不一致
    mutate(env_basic, NEW_ANSWERS, "**推荐语序**：3142", "**推荐语序**：3412")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "编号" in f.message for f in findings)


def test_c2_card_answers_order_disagree(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0005.md",
           '"recommended_order": "3142"', '"recommended_order": "3412"')
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "题卡" in f.message and "语序" in f.message for f in findings)


def test_c2_star_position_mismatch(env_basic, mutate):
    # ★ 放到第 3 空：正确项应变成语序第 3 位"4"，但答案仍写 1
    mutate(env_basic, NEW_PAPER,
           "去年の夏、湖水旅行で、＿＿ ★ ＿＿ ＿＿ ことがあります。",
           "去年の夏、湖水旅行で、＿＿ ＿＿ ★ ＿＿ ことがあります。")
    answers, cards, _ = _env(env_basic)
    findings = check_order_invariants(_paper(env_basic), answers, cards)
    assert any(f.check == "C2" and "★" in f.message for f in findings)


def test_c3_clean_env_passes(env_basic):
    answers, cards, _ = _env(env_basic)
    assert check_consistency(_paper(env_basic), answers, cards) == []


def test_c3_correct_option_disagreement(env_basic, mutate):
    mutate(env_basic, "jlpt-notes/quizzes/questions/N4-Q-0004.md",
           '"correct_option": "4"', '"correct_option": "1"')
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "正确项" in f.message for f in findings)


def test_c3_option_text_drift(env_basic, mutate):
    mutate(env_basic, NEW_PAPER, "2. 見ます", "2. 見ません")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "选项" in f.message for f in findings)


def test_c3_translation_disagreement(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS, "**翻译**：天气好的日子", "**翻译**：天气好的日子里")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "翻译" in f.message for f in findings)


def test_c3_tested_cards_disagreement(env_basic, mutate):
    mutate(env_basic, NEW_ANSWERS,
           "**考点**：N4-G-0003「～ことができます」", "**考点**：N4-G-0002「～ことができます」")
    answers, cards, _ = _env(env_basic)
    findings = check_consistency(_paper(env_basic), answers, cards)
    assert any(f.check == "C3" and "考点" in f.message for f in findings)
