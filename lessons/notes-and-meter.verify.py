"""notes-and-meter の検算（sympy の分数）

使い方: python3 lessons/notes-and-meter.verify.py
- 四分音符を 1 拍として、音符の長さ・付点・拍子の主張を分数で 1 つずつ確かめる
- 台本の表（notes-1・dot-1・meter-2）、棒グラフ（notes-2）、数直線（notes-3・meter-3）、問いの答えを照合する
"""
import os
import re
import sys

import yaml
from sympy import Rational as R

HERE = os.path.dirname(os.path.abspath(__file__))
doc = yaml.safe_load(open(os.path.join(HERE, "notes-and-meter.yaml"), encoding="utf-8"))
scenes = {sc["id"]: sc for ch in doc["chapters"] for sc in ch["scenes"]}
fails, oks = [], 0

# 全音符を 1 とした長さ（全音符の 2 分の 1 が二分音符…）。四分音符を 1 拍とすると、拍 = 長さ × 4
WHOLE = {"全音符": R(1), "二分音符": R(1, 2), "四分音符": R(1, 4), "八分音符": R(1, 8), "十六分音符": R(1, 16)}
BEAT = R(1, 4)


def beats(name):
    if name.startswith("付点"):
        return beats(name[2:]) * R(3, 2)
    return WHOLE[name] / BEAT


def check(name, got, want):
    global oks
    if got == want:
        oks += 1
        print(f"OK  {name}: {got}")
    else:
        fails.append(name)
        print(f"NG  {name}: {got} ≠ {want}")


def num(s):
    return R(str(s).strip())


# notes-1 の表：拍と、全音符を 1 としたときの長さ
for r in scenes["notes-1"]["blocks"][1]["rows"]:
    name, b, w = r["cells"]
    check(f"notes-1 {name} の拍", num(b), beats(name))
    check(f"notes-1 {name}（全音符 = 1）", num(w), WHOLE[name])

# notes-2 の棒グラフ
blk = scenes["notes-2"]["blocks"][1]
for name, v in zip(blk["labels"], blk["series"][0]["values"]):
    check(f"notes-2 {name}", num(v), beats(name))
check("notes-2 全音符に十六分音符は 16 個", WHOLE["全音符"] / WHOLE["十六分音符"], 16)

# notes-3：4分の4拍子の 1 小節 = 4 拍を、全・二分・四分で分けた始まりの位置
nl = scenes["notes-3"]["blocks"][1]
check("notes-3 1 小節の拍", num(nl["range"][1]) - num(nl["range"][0]), 4)
for name in ("全音符", "二分音符", "四分音符"):
    starts = sorted(num(p["value"]) for p in nl["points"] if p["label"] == name)
    want = [beats(name) * k for k in range(int(4 / beats(name)))]
    check(f"notes-3 {name} の始まり", starts, want)

# dot-1 の表：「2 × 1.5 = 3」
for r in scenes["dot-1"]["blocks"][1]["rows"]:
    name, expr = r["cells"]
    a, k, c = re.fullmatch(r"([\d.]+) × ([\d.]+) = ([\d.]+)", expr).groups()
    check(f"dot-1 {name} のもと", num(a), beats(name[2:]))
    check(f"dot-1 {name} の倍率", num(k), R(3, 2))
    check(f"dot-1 {name}", num(c), beats(name))

# meter-2 の表：拍子・1 拍の音符・1 小節の拍の数
for r in scenes["meter-2"]["blocks"][1]["rows"]:
    meter, unit, n = r["cells"]
    lower, upper = (int(x) for x in re.fullmatch(r"(\d)分の(\d)拍子", meter).groups())
    bar = R(upper, lower) / BEAT                      # 1 小節の長さ（四分音符 = 1 拍）
    check(f"meter-2 {meter} の 1 拍の長さ × 拍の数", beats(unit) * int(n), bar)
    if lower == 4:
        check(f"meter-2 {meter} の 1 拍", unit, "四分音符")
        check(f"meter-2 {meter} の拍の数", int(n), upper)

# meter-3：8分の6拍子 = 八分音符 6 つを 3 つずつ 2 拍。1 拍 = 付点四分音符
nl = scenes["meter-3"]["blocks"][1]
spans = [(num(s["from"]), num(s["to"])) for s in nl["spans"]]
check("meter-3 帯は 3 つずつ", [b - a for a, b in spans], [3, 3])
check("meter-3 八分音符 3 つ = 付点四分音符", 3 * beats("八分音符"), beats("付点四分音符"))

# 問い
check("check-1 4分の3拍子の八分音符", (R(3, 4) / BEAT) / beats("八分音符"), 6)
check("check-2 付点二分音符 + 四分音符", beats("付点二分音符") + beats("四分音符"), 4)

print(f"\n結果：OK {oks} 件・NG {len(fails)} 件")
sys.exit(1 if fails else 0)
