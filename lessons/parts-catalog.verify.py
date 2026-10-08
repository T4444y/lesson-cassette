"""parts-catalog の数値の主張を sympy で検算する（台詞・画面）。

使い方: python3 lessons/parts-catalog.verify.py
グラフの数値は説明用に作った例なので、台詞との食い違いだけを確かめる。
"""
import os
import sys

import yaml
from sympy import Rational as R, symbols

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "parts-catalog.yaml")
doc = yaml.safe_load(open(SRC, encoding="utf-8"))
sc = {s["id"]: s for ch in doc["chapters"] for s in ch["scenes"]}
blk = lambda sid, t: next(b for b in sc[sid]["blocks"] if b["type"] == t)
ok = []


def check(cond, msg):
    if not bool(cond):
        raise SystemExit(f"NG: {msg}")
    ok.append(msg)


def amount(s):
    s = str(s)
    if s.endswith("%"):
        return R(s[:-1]) / 100
    if "/" in s:
        a, b = s.split("/")
        return R(int(a), int(b))
    return R(s)


# convert-1: 各行が同じ大きさ
for r in blk("convert-1", "table")["rows"]:
    vals = {amount(c) for c in r["cells"]}
    check(len(vals) == 1, f"convert-1: {' = '.join(r['cells'])}")
# matrix-1: 九九の表と、3 × 4 = 12
t = blk("matrix-1", "table")
for row in t["rows"]:
    cells = row["cells"] if isinstance(row, dict) else row
    for h, c in zip(t["head"][1:], cells[1:]):
        check(int(cells[0]) * int(h) == int(c), f"matrix-1: {cells[0]} × {h} = {c}")
check(3 * 4 == 12, "matrix-1 台詞: 3 × 4 = 12")
# nl-1: 0.35 = 35%
check(R("0.35") * 100 == 35, "nl-1: 0.35 = 35%")
# bar-1: いちばん長いのは木曜日の 60 分
b = blk("bar-1", "chart")
v = b["series"][0]["values"]
check(max(v) == 60 and b["labels"][v.index(60)] == "木" and v.count(60) == 1, "bar-1: 最大は木曜日の 60 分")
# line-1: A 店は 7 月まで増え 8 月に減る、B 店は 8 月に 175 人で A 店を上回る
c = blk("line-1", "chart")
A, B = (s["values"] for s in c["series"])
check(all(A[i] < A[i + 1] for i in range(3)) and A[4] < A[3], "line-1: A 店は 7 月まで増え、8 月に減った")
check(B[4] == 175 and B[4] > A[4] and all(B[i] <= A[i] for i in range(4)), "line-1: B 店は 8 月に 175 人で、初めて A 店を上回った")
# seg-1: y = 2x + 1、(1, 3) から右へ 1・上へ 2 で (2, 5)
x = symbols("x")
f = 2 * x + 1
check(f.subs(x, 1) == 3 and f.subs(x, 2) == 5, "seg-1: (1, 3) と (2, 5) は y = 2x + 1 の上")
curves = blk("seg-1", "plot")["curves"]
run, rise = curves[1], curves[2]
check(run["from"] == [1, 3] and run["to"] == [2, 3], "seg-1: 右へ 1 の線分")
check(rise["from"] == [2, 3] and rise["to"] == [2, 5], "seg-1: 上へ 2 の線分")
check((5 - 3) / (2 - 1) == 2, "seg-1: 傾き 2")
for m in ok:
    print("OK ", m)
print(f"\n{len(ok)} 件すべて一致")
