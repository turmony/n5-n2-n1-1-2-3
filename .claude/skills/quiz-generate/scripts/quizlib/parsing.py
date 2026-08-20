import re

from .models import AnswerEntry, Paper, PaperQuestion

QUESTION_HEADER_RE = re.compile(r"^#{3,4}\s*(\d+)[.．]\s*(.*)$")
SECTION_RE = re.compile(r"^##\s*第([一二三])部分")
OPTION_RE = re.compile(r"^(\d)[.．]\s*(.+)$")
ANSWER_HEADER_RE = re.compile(r"^###\s*第\s*(\d+)\s*题[（(]([NS]\d+-Q-\d{4})[）)]")
FIELD_RE = re.compile(r"^\*\*(题目|翻译|考点|推荐语序|正确项|正确接续|解析)\*\*[：:]\s*(.*)$")
GRAMMAR_ID_RE = re.compile(r"[NS]\d+-G-\d{4}")
ORDER_RE = re.compile(r"^(\d{4})[（(]")
CORRECT_RE = re.compile(r"^(\d)")
OPTION_ANA_RE = re.compile(r"^-?\s*选项\s*(\d)[（(](.+?)[）)]\s*[：:]")

_SECTION_NAMES = {"一": "form", "二": "order", "三": "cloze"}


def _star_pos(stem: str) -> int | None:
    """数题干里 ★ 前出现的 ＿＿ 数量，★ 位置＝空位序号（1 起）。"""
    if "★" not in stem:
        return None
    pos = 0
    for token in re.finditer(r"＿＿|★", stem):
        pos += 1
        if token.group(0) == "★":
            return pos
    return None


def parse_paper(text: str) -> Paper:
    paper = Paper(raw_text=text)
    section = "form"
    current = None
    seen_option_lines_after_header = False
    for raw in text.splitlines():
        line = raw.rstrip()
        m = SECTION_RE.match(line)
        if m:
            section = _SECTION_NAMES[m.group(1)]
            continue
        if line.startswith("## 答案填写区"):
            break
        m = QUESTION_HEADER_RE.match(line)
        if m and not OPTION_RE.match(line):
            current = PaperQuestion(number=int(m.group(1)), section=section,
                                    stem=m.group(2).strip())
            current.star_pos = _star_pos(current.stem)
            paper.questions.append(current)
            seen_option_lines_after_header = False
            continue
        if current is not None:
            om = OPTION_RE.match(line)
            if om:
                current.options[om.group(1)] = om.group(2).strip()
                seen_option_lines_after_header = True
    return paper


def parse_answers(text: str) -> list[AnswerEntry]:
    entries: list[AnswerEntry] = []
    current: AnswerEntry | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = ANSWER_HEADER_RE.match(line)
        if m:
            current = AnswerEntry(number=int(m.group(1)), card_id=m.group(2))
            entries.append(current)
            continue
        if current is None:
            continue
        fm = FIELD_RE.match(line)
        if fm:
            key, value = fm.group(1), fm.group(2).strip()
            if key == "题目":
                current.stem = value
            elif key == "翻译":
                current.translation = value
            elif key == "考点":
                current.grammar_ids = GRAMMAR_ID_RE.findall(value)
            elif key == "推荐语序":
                om = ORDER_RE.match(value)
                current.order = om.group(1) if om else None
            elif key == "正确项":
                cm = CORRECT_RE.match(value)
                current.correct_option = cm.group(1) if cm else ""
            elif key == "正确接续":
                current.conjugation = value
            elif key == "解析":
                current.analysis = value
            continue
        om = OPTION_ANA_RE.match(line)
        if om:
            current.option_analyses[om.group(1)] = om.group(2).strip()
    return entries
