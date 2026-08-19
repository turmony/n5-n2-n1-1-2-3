"""题目查重：比对 quizzes/questions/ 全部题卡的题干，找出相同或高度相似的题。

用法（uv run python work/quiz_dedup_check.py）：
- 无参数：全库两两比对，报告内部重复
- --new-from 146：把 N4-Q-0146 及以后的题卡视为新题，只与更早的题卡比对（出卷定稿前用）

按题型构造比对键，避免结构性误报：
- grammar_form：题干整句
- sentence_composition：排序框架＋语块集合（框架相同但语块不同＝不同题）
- text_grammar／reading_comprehension：整段 prompt 去掉（NN）空格编号——
  同一篇文章的不同空格（键相同、空格号不同）不算重复；同一空格再现才算。

判定：归一化（去空白与标点）后 difflib 相似度 ≥ 阈值（默认 0.72）视为「相同或类似」。
同一考点再考是允许的；本脚本只看题干文本本身。
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
        })
    return cards


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
    args = ap.parse_args()

    cards = load_cards()
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
        return
    print("发现 %d 对疑似重复（阈值 %.2f）：" % (len(hits), args.threshold))
    for r, aid, bid, ha, hb in sorted(hits, reverse=True):
        print("  %.2f  %s <-> %s" % (r, aid, bid))
        print("        A: %s" % ha)
        print("        B: %s" % hb)
    sys.exit(1)


if __name__ == "__main__":
    main()
