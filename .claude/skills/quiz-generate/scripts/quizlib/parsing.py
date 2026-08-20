import json
import re
from pathlib import Path

from .models import AnswerEntry, Paper, PaperQuestion, QuestionCard

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


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def extract_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("frontmatter not found")
    return json.loads(m.group(1))


def load_question_cards(quizzes_dir: Path) -> dict:
    """装载题库全部题卡。

    - frontmatter 损坏的卡也登记（fm 用空 dict、id 取文件名 stem），
      保证重复/接缝检查仍覆盖它；损坏原因由 load_question_card_errors 单独报。
    - 同 id 再次出现（不同文件）时，后一个文件覆盖 cards[cid]，
      并把该 id 追加进特殊键 "__duplicates__"（value 为 list[str]），
      由 C1 报「题卡 id 重复」——拦截卷三/卷四 ID 覆盖冲突类事故。
    """
    cards: dict = {}
    for p in sorted((quizzes_dir / "questions").glob("*.md")):
        try:
            fm = extract_frontmatter(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            fm = None
        cid = str((fm or {}).get("id") or p.stem)
        card = QuestionCard(id=cid, path=str(p), frontmatter=fm or {})
        if cid in cards:
            cards[cid] = card
            cards.setdefault("__duplicates__", []).append(cid)
        else:
            cards[cid] = card
    return cards


def load_question_card_errors(quizzes_dir: Path) -> list:
    """返回 [(path, 原因)]，frontmatter 损坏的卡由 C1 报告。"""
    errors = []
    for p in sorted((quizzes_dir / "questions").glob("*.md")):
        try:
            extract_frontmatter(p.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append((p.name, str(exc)))
    return errors


def load_grammar_ids(notes_root: Path) -> set:
    ids = set()
    for p in sorted((notes_root / "grammar").glob("*/*.md")):
        try:
            fm = extract_frontmatter(p.read_text(encoding="utf-8"))
            ids.add(str(fm.get("id") or p.stem))
        except (ValueError, json.JSONDecodeError):
            ids.add(p.stem)
    return ids
