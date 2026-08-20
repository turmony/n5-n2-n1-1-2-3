import re

from .models import AnswerEntry, ERROR, Finding, QuestionCard
from .parsing import load_question_card_errors

CARD_ID_RE = re.compile(r"^[NS]\d+-Q-\d{4}$")


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
    same_level = [cid for cid in cards if cid.startswith(prefix)]
    new_set = set(new_ids)
    old_max = max((_numeric(c) for c in same_level if c not in new_set), default=0)
    nums = sorted(_numeric(c) for c in set(new_ids) if c.startswith(prefix))
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
