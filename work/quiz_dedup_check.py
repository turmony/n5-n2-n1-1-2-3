"""题目查重：比对 quizzes/questions/ 全部题卡的题干，找出相同或高度相似的题。

用法（uv run python work/quiz_dedup_check.py）：
- 无参数：全库两两比对，报告内部重复
- --new-from 146：把 N4-Q-0146 及以后的题卡视为新题，只与更早的题卡比对（出卷定稿前用）
- --junction-only：只运行题干冗余字符检查（空格与选项拼合），不做相似度查重

按题型构造比对键，避免结构性误报：
- grammar_form：题干整句
- sentence_composition：排序框架＋语块集合（框架相同但语块不同＝不同题）
- text_grammar／reading_comprehension：整段 prompt 去掉（NN）空格编号——
  同一篇文章的不同空格（键相同、空格号不同）不算重复；同一空格再现才算。

判定：归一化（去空白与标点）后 difflib 相似度 ≥ 阈值（默认 0.72）视为「相同或类似」。
同一考点再考是允许的；本脚本只看题干文本本身。

题干冗余字符检查（2026-08-20 新增）：题干空格与任一选项拼合后，接缝处不得出现
重复字符——选项首字与空格前一字相同、或选项末字与空格后一字相同，均判为缺陷。
例：选项「ている」＋题干「（　）るです」→「ているるです」，「る」重复。
"""

import argparse
import glob
import json
import os
import re
import sys
from difflib import SequenceMatcher

ROOT = os.path.join(os.path.dirname(__file__), "..", "jlpt-notes", "quizzes", "questions")

_STRIP = re.compile(r"[\s。，、；：？！「」『』（）()．·…～★＿　]")
_BLANKNUM = re.compile(r"（(\d+)）")
_FORM_BLANK = re.compile(r"（[ 　]*）|\([ ]*\)")

# 接缝重复但属于合法日语拼合的已知组合（豁免表）：
# ("で","で")：まで＋です／でも 等（「九時から七時（　）です」选まで＝までです）
_LEGIT_JUNCTIONS = {("で", "で")}


def make_key(d):
    prompt = d["prompt"]
    typ = d["item_type"]
    if typ == "sentence_composition":
        frame = prompt.splitlines()[-1]
        chunks = "".join(sorted(d["options"].values()))
        return typ, _STRIP.sub("", frame + chunks), None
    m = _BLANKNUM.search(prompt)
    blank = m.group(1) if m else None
    text = _BLANKNUM.sub("（＃）", prompt)
    return typ, _STRIP.sub("", text), blank


def load_cards():
    cards = []
    for f in sorted(glob.glob(os.path.join(ROOT, "*.md"))):
        text = open(f, encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        try:
            d = json.loads(m.group(1))
        except Exception:
            print("WARN: JSON 解析失败，跳过 %s" % f, file=sys.stderr)
            continue
        qid = d["id"]
        typ, key, blank = make_key(d)
        cards.append({
            "id": qid, "num": int(qid.split("-")[2]), "is_n4": qid.startswith("N4"),
            "typ": typ, "key": key, "blank": blank,
            "head": d["prompt"].splitlines()[-1][:46],
            "options": d.get("options") or {}, "prompt": d["prompt"],
        })
    return cards


def junction_defects(card):
    """题干冗余字符检查：空格与选项拼合的接缝处不得出现重复字符。

    返回缺陷列表 [(选项号, 选项, 重复字, 位置说明)]；sentence_composition 无空格代入，跳过。
    """
    typ, prompt, opts = card["typ"], card["prompt"], card["options"]
    if typ == "sentence_composition":
        return []
    if typ == "text_grammar" or typ == "reading_comprehension":
        m = _BLANKNUM.search(prompt)
        if not m:
            return []
        nn = m.group(1)
        m2 = re.search("（%s）" % nn, prompt[m.end():])
        if not m2:
            return []
        s, e = m.end() + m2.start(), m.end() + m2.end()
    else:
        m = _FORM_BLANK.search(prompt)
        if not m:
            return []
        s, e = m.span()
    prefix, suffix = prompt[:s], prompt[e:]
    defects = []
    for label in sorted(opts):
        opt = opts[label].strip()
        if not opt:
            continue
        if prefix and opt[0] == prefix[-1] and (prefix[-1], opt[0]) not in _LEGIT_JUNCTIONS:
            defects.append((label, opt, opt[0], "选项首字与空格前一字「%s」重复" % prefix[-1]))
        if suffix and opt[-1] == suffix[0] and (opt[-1], suffix[0]) not in _LEGIT_JUNCTIONS:
            defects.append((label, opt, suffix[0], "选项末字与空格后一字「%s」重复" % suffix[0]))
    return defects


def is_dup(a, b, threshold):
    if not a["key"] or not b["key"]:
        return None
    r = SequenceMatcher(None, a["key"], b["key"]).ratio()
    if r < threshold:
        return None
    if r >= 0.999 and a["blank"] and b["blank"] and a["blank"] != b["blank"]:
        return None  # 同一篇文章的不同空格，结构性共享，不算重复
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-from", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=0.72)
    ap.add_argument("--junction-only", action="store_true", help="只运行题干冗余字符检查")
    args = ap.parse_args()

    cards = load_cards()

    junction_bad = []
    for c in cards:
        for label, opt, ch, why in junction_defects(c):
            junction_bad.append((c["id"], label, opt, ch, why))
    if junction_bad:
        print("题干冗余字符检查：发现 %d 处接缝重复缺陷：" % len(junction_bad))
        for qid, label, opt, ch, why in junction_bad:
            print("  %s 选项%s「%s」：%s" % (qid, label, opt, why))
    else:
        print("题干冗余字符检查通过：%d 张题卡接缝无重复" % len(cards))

    if args.junction_only:
        sys.exit(1 if junction_bad else 0)

    if args.new_from is not None:
        new = [c for c in cards if c["is_n4"] and c["num"] >= args.new_from]
        old = [c for c in cards if not (c["is_n4"] and c["num"] >= args.new_from)]
        pairs = [(a, b) for a in new for b in old]
    else:
        pairs = [(cards[i], cards[j]) for i in range(len(cards)) for j in range(i + 1, len(cards))]

    hits = []
    for a, b in pairs:
        if a["typ"] != b["typ"]:
            continue
        r = is_dup(a, b, args.threshold)
        if r:
            hits.append((r, a["id"], b["id"], a["head"], b["head"]))

    if not hits:
        print("查重通过：未发现相同或类似题干（阈值 %.2f，比对 %d 对）" % (args.threshold, len(pairs)))
        sys.exit(1 if junction_bad else 0)
    print("发现 %d 对疑似重复（阈值 %.2f）：" % (len(hits), args.threshold))
    for r, aid, bid, ha, hb in sorted(hits, reverse=True):
        print("  %.2f  %s <-> %s" % (r, aid, bid))
        print("        A: %s" % ha)
        print("        B: %s" % hb)
    sys.exit(1 if (hits or junction_bad) else 0)


if __name__ == "__main__":
    main()
