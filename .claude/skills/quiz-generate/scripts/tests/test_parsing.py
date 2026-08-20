from quizlib.parsing import parse_paper, parse_answers


def _paper_text(env_basic):
    return (env_basic / "jlpt-notes/quizzes/papers/2026-01-02-n4-coverage-test-1.md").read_text(encoding="utf-8")


def _answers_text(env_basic):
    return (env_basic / "jlpt-notes/quizzes/answers/2026-01-02-n4-coverage-test-1-answers.md").read_text(encoding="utf-8")


def test_parse_paper_sections_and_counts(env_basic):
    paper = parse_paper(_paper_text(env_basic))
    sections = [q.section for q in paper.questions]
    assert sections == ["form", "form", "order", "cloze"]
    assert [q.number for q in paper.questions] == [1, 2, 3, 4]


def test_parse_paper_form_question_options(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[0]
    assert q.stem == "何回も説明した（　）、彼はまだ分かっていない。"
    assert q.options == {"1": "のに", "2": "ので", "3": "から", "4": "まで"}
    assert q.star_pos is None


def test_parse_paper_order_star_pos(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[2]
    assert q.section == "order"
    assert q.star_pos == 2
    assert q.options["3"] == "ガイドさんの"


def test_parse_paper_cloze_empty_stem_with_options(env_basic):
    q = parse_paper(_paper_text(env_basic)).questions[3]
    assert q.section == "cloze"
    assert q.stem == ""
    assert len(q.options) == 4


def test_parse_paper_ignores_answer_sheet_area(env_basic):
    paper = parse_paper(_paper_text(env_basic))
    assert len(paper.questions) == 4  # 答案填写区里的 "1-, 2-" 不算题目


def test_parse_paper_h2_interlude_stops_option_ingestion(env_basic):
    # 真实卷格式：第一部分与第二部分之间有「排序规则速览」H2 插页，其 1.～3.
    # 编号行不是上一题（第 2 题）的选项，也不得计入题量/选项数
    paper = parse_paper(_paper_text(env_basic))
    assert len(paper.questions) == 4
    q2 = paper.questions[1]
    assert q2.options == {"1": "見て", "2": "見ます", "3": "見た", "4": "見る"}


def test_parse_answers_fields(env_basic):
    entries = parse_answers(_answers_text(env_basic))
    assert len(entries) == 4
    e1 = entries[0]
    assert e1.number == 1
    assert e1.card_id == "N4-Q-0003"
    assert e1.grammar_ids == ["N4-G-0001"]
    assert e1.correct_option == "1"
    assert e1.translation.startswith("明明")
    assert "のに" in e1.analysis
    assert set(e1.option_analyses) == {"2", "3", "4"}


def test_parse_answers_order_entry(env_basic):
    e3 = parse_answers(_answers_text(env_basic))[2]
    assert e3.card_id == "N4-Q-0005"
    assert e3.order == "3142"
    assert e3.correct_option == "1"
    assert e3.conjugation.startswith("動詞た形")
