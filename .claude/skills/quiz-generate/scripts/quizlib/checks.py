import re

from .models import AnswerEntry, ERROR, Finding, QuestionCard, WARN
from .parsing import load_question_card_errors

CARD_ID_RE = re.compile(r"^[NS]\d+-Q-\d{4}$")
BLOCK_DIGIT_RE = re.compile(r"[（(]\s*([1-4])\s*[）)]")


def norm(s: str) -> str:
    """去全部空白（含全角空格）与 ** 加粗标记，用于跨文件文本比对。"""
    return re.sub(r"(\s|\*\*)+", "", s or "")


def _numeric(cid: str) -> int:
    return int(cid.rsplit("-", 1)[1])


def check_card_ids(answers: list[AnswerEntry], cards: dict, level: str,
                   quizzes_dir=None) -> list[Finding]:
    findings = []
    if "__duplicates__" in cards:
        for cid in cards["__duplicates__"]:
            findings.append(Finding("C1", ERROR, cid, "题卡 id 重复：存在多个同名 id 文件"))
    if quizzes_dir is not None:
        for name, why in load_question_card_errors(quizzes_dir):
            findings.append(Finding("C1", ERROR, name, f"frontmatter 无效：{why}"))
    for e in answers:
        if not CARD_ID_RE.match(e.card_id):
            findings.append(Finding("C1", ERROR, f"题{e.number}", f"题卡 ID 格式非法：{e.card_id}"))
            continue
        if e.card_id not in cards:
            findings.append(Finding("C1", ERROR, f"题{e.number}", f"答案引用的题卡不存在：{e.card_id}"))
            continue
        card = cards[e.card_id]
        if card.level and card.level != level:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"题卡级别不符：{e.card_id} 是 {card.level}，应为 {level}"))
        for field_name in ("prompt", "correct_option", "correct_explanation"):
            if not getattr(card, field_name):
                findings.append(Finding("C1", ERROR, f"题{e.number}",
                                        f"题卡 {e.card_id} 缺必填字段：{field_name}"))
        if len(card.options) != 4:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"题卡 {e.card_id} 选项数≠4（{len(card.options)}）"))
        if card.item_type == "sentence_composition" and not card.recommended_order:
            findings.append(Finding("C1", ERROR, f"题{e.number}",
                                    f"排序题卡 {e.card_id} 缺 recommended_order"))
    # 新卡段接缝：新卡号必须整体大于旧卡号且自身连续
    new_ids = [e.card_id for e in answers if e.card_id in cards]
    prefix = f"{level}-Q-"
    # 数值比较只纳入格式合法的 id（畸形 id——如坏卡退回的 stem——由上方格式检查
    # 与 frontmatter 检查负责报告），避免 int() 抛 ValueError 使校验器崩溃
    same_level = [cid for cid in cards if CARD_ID_RE.match(cid) and cid.startswith(prefix)]
    new_set = set(new_ids)
    old_max = max((_numeric(c) for c in same_level if c not in new_set), default=0)
    nums = sorted(_numeric(c) for c in set(new_ids)
                  if CARD_ID_RE.match(c) and c.startswith(prefix))
    if nums:
        if nums[0] <= old_max:
            findings.append(Finding("C1", ERROR, new_ids[0],
                                    f"新题卡号 {new_ids[0]} 未接续既有最大号（>{old_max:04d}）"))
        if nums != list(range(nums[0], nums[0] + len(nums))):
            findings.append(Finding("C1", ERROR, prefix + str(nums[0]),
                                    f"新题卡号不连续：{nums}"))
    return findings


def check_grammar_refs(answers: list[AnswerEntry], grammar_ids: set, level: str) -> list[Finding]:
    findings = []
    for e in answers:
        for gid in e.grammar_ids:
            if gid not in grammar_ids:
                findings.append(Finding("C4", ERROR, f"题{e.number}", f"考点卡不存在：{gid}"))
            elif not gid.startswith(f"{level}-G-"):
                findings.append(Finding("C4", ERROR, f"题{e.number}",
                                        f"考点卡级别不符：{gid} 应为 {level} 语法卡"))
        if not e.grammar_ids:
            findings.append(Finding("C4", ERROR, f"题{e.number}", "考点字段未解析出卡号"))
    return findings


def check_order_invariants(paper, answers, cards) -> list[Finding]:
    findings = []
    order_entries = {e.number: e for e in answers if e.order is not None}
    order_questions = {q.number: q for q in paper.questions if q.section == "order"}
    for number, e in sorted(order_entries.items()):
        loc = f"题{number} / {e.card_id}"
        card = cards.get(e.card_id)
        order = e.order
        if sorted(order) != list("1234"):
            findings.append(Finding("C2", ERROR, loc, f"推荐语序 {order} 不是 1–4 的合法排列"))
            continue
        # 解析文字里的块编号序列必须等于语序串（如 …(3)／(1)／(4)／(2)… ↔ 3142）
        digits = BLOCK_DIGIT_RE.findall(e.analysis)
        if digits and "".join(digits) != order:
            findings.append(Finding("C2", ERROR, loc,
                f"解析块编号 {''.join(digits)} 与推荐语序 {order} 不一致（数字串笔误）"))
        if card is not None and card.recommended_order:
            if card.recommended_order != order:
                findings.append(Finding("C2", ERROR, loc,
                    f"题卡语序 {card.recommended_order} 与答案语序 {order} 不一致"))
            cdigits = BLOCK_DIGIT_RE.findall(card.correct_explanation)
            if cdigits and "".join(cdigits) != order:
                findings.append(Finding("C2", ERROR, loc,
                    f"题卡解析块编号 {''.join(cdigits)} 与推荐语序 {order} 不一致"))
        q = order_questions.get(number)
        if q is None:
            findings.append(Finding("C2", ERROR, loc, "答案含语序但试卷无对应排序题"))
            continue
        if q.star_pos is None:
            findings.append(Finding("C2", ERROR, loc, "试卷排序题缺 ★ 标记"))
        else:
            expected = order[q.star_pos - 1]
            if e.correct_option and e.correct_option != expected:
                findings.append(Finding("C2", ERROR, loc,
                    f"★ 位（第{q.star_pos}空）语序数字为 {expected}，但正确项写 {e.correct_option}"))
    for number in sorted(set(order_questions) - set(order_entries)):
        findings.append(Finding("C2", ERROR, f"题{number}", "排序题缺推荐语序"))
    return findings


def check_consistency(paper, answers, cards) -> list[Finding]:
    findings = []
    paper_by_number = {q.number: q for q in paper.questions}
    for e in answers:
        loc = f"题{e.number} / {e.card_id}"
        card = cards.get(e.card_id)
        q = paper_by_number.get(e.number)
        if card is None or q is None:
            continue  # C1/C5 负责缺卡缺题
        # 选项三方一致（试卷 ↔ 题卡）
        for opt, text in q.options.items():
            ct = card.options.get(opt, "")
            if ct and norm(ct) != norm(text):
                findings.append(Finding("C3", ERROR, loc,
                    f"选项 {opt} 不一致：试卷「{text}」≠ 题卡「{ct}」"))
        # 正确项：题卡 ↔ 答案
        if card.correct_option and e.correct_option and card.correct_option != e.correct_option:
            findings.append(Finding("C3", ERROR, loc,
                f"正确项不一致：题卡 {card.correct_option} ≠ 答案 {e.correct_option}"))
        # 题干：试卷题干 ⊆ 题卡 prompt；答案题干 ⊆ 题卡 prompt（完形题卡含全文）。
        # 排序题答案的题目是「见试卷第 N 题框架」式指引（fixture 与真实卷同一约定），
        # 指向试卷而非题面文本，无文本可比对，跳过
        if q.stem:
            if norm(q.stem) not in norm(card.prompt):
                findings.append(Finding("C3", ERROR, loc, "试卷题干未出现在题卡 prompt 中"))
        if e.stem and "见试卷" not in e.stem and norm(e.stem) not in norm(card.prompt):
            findings.append(Finding("C3", WARN, loc, "答案题干未出现在题卡 prompt 中"))
        # 翻译：题卡 ↔ 答案（题卡缺字段则跳过）
        if card.translation and e.translation and norm(card.translation) != norm(e.translation):
            findings.append(Finding("C3", ERROR, loc, "翻译不一致：题卡与答案文件不同"))
        # 考点：题卡 tested_cards ↔ 答案 grammar_ids（题卡缺字段降级为 warn）
        if card.tested_cards:
            if set(card.tested_cards) != set(e.grammar_ids):
                findings.append(Finding("C3", ERROR, loc,
                    f"考点不一致：题卡 {card.tested_cards} ≠ 答案 {e.grammar_ids}"))
        elif e.grammar_ids:
            findings.append(Finding("C3", WARN, loc, "题卡缺 tested_cards 字段，无法核对考点"))
        # 答案正确项括号里的选项文字应与试卷选项一致
        m = re.match(r"^(\d)[（(](.+?)[）)]$", e.correct_option_text)
        if m:
            opt, text = m.group(1), m.group(2)
            pt = q.options.get(opt, "")
            if pt and norm(pt) != norm(text):
                findings.append(Finding("C3", WARN, loc,
                    f"正确项 {opt} 文字「{text}」与试卷选项「{pt}」不同"))
    return findings
