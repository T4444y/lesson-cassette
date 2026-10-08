"""speed-distance-time.yaml の数値の検算（sympy）。

使い方：python3 lessons/speed-distance-time.verify.py
同じフォルダの台本を読み、画面（表・数直線・グラフ・式）と台詞・問いの答えにある数の主張を確かめる。
qa.py が照合しないもの（単位つき見出しの 2 軸の表、速さの換算表）もここで確かめる。
"""
import re
import sys
from pathlib import Path

import yaml
from sympy import Rational, nsimplify

HERE = Path(__file__).resolve().parent
doc = yaml.safe_load((HERE / "speed-distance-time.yaml").read_text(encoding="utf-8"))
scenes = {s["id"]: s for ch in doc["chapters"] for s in ch["scenes"]}

ok = ng = 0


def check(cond, msg):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        ng += 1
        print(f"  NG  {msg}")


def R(x):
    return nsimplify(str(x).replace(",", ""), rational=True)


def num(s):
    """文字列の最初の数（小数可）を有理数で返す。"""
    m = re.search(r"\d+(?:\.\d+)?", str(s))
    return R(m.group()) if m else None


def calc(expr):
    """'240 ÷ 3 = 80' の形を確かめる。(左辺の値, 右辺の値) を返す。"""
    e = expr.replace("÷", "/").replace("×", "*").replace("＝", "=").replace("−", "-")
    left, right = e.split("=")[-2], e.split("=")[-1]
    left = re.sub(r"[^\d\.\+\-\*/ ]", "", left)
    return R(eval(left, {"__builtins__": {}})) if left.strip() else None, num(right)


def block(scene, t, i=0):
    return [b for b in scenes[scene]["blocks"] if b["type"] == t][i]


def lines(scene):
    return " ".join(l["text"] for l in scenes[scene]["lines"])


KM = 1000  # 1km = 1000m
HOUR = 60  # 1時間 = 60分
MIN = 60   # 1分 = 60秒

print("1. どちらが速い（speed-1・speed-2）")
a_speed = Rational(300, 5)
b_speed = Rational(240, 3)
check(a_speed == 60 and b_speed == 80, "A：300 ÷ 5 = 60、B：240 ÷ 3 = 80（分速）")
check(b_speed > a_speed, "B のほうが速い")
for item in block("speed-2", "steps")["items"]:
    l, r = calc(item["title"])
    check(l == r, f"steps「{item['title']}」")
    check(f"1分あたり{r}m" == item["note"], f"steps の note「{item['note']}」")
bar = block("speed-2", "chart")
check(bar["series"][0]["values"] == [60, 80], f"棒グラフの値 {bar['series'][0]['values']} = [A, B]")
check("5分で300m" in str(block("speed-1", "compare")["left"]) and "3分で240m" in str(block("speed-1", "compare")["right"]), "compare の左右の数")

print("2. 二重数直線（rel-1・rel-2）")
for sid in ("rel-1", "rel-2"):
    nl = block(sid, "numberline")
    check(nl["second"]["factor"] == b_speed, f"{sid}: 下の目盛り = 上 × 80（分速80m）")
    for p in nl["points"]:
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*(分|m)", p["label"])
        for v, unit in nums:
            want = p["value"] if unit == "分" else p["value"] * b_speed
            check(R(v) == want, f"{sid}: 点 {p['value']} のラベル「{p['label']}」の {v}{unit}")
check(80 * 3 == 240, "rel-1 台詞：80 × 3 で240m")
check(Rational(400, 80) == 5, "rel-2 台詞：400 ÷ 80 で5分")

print("3. 3つの式の表（rel-3）")
tb = block("rel-3", "table")
for row in tb["rows"]:
    cells = row["cells"]
    l, r = calc(cells[2])
    check(l == r, f"rel-3 例「{cells[2]}」")
speed, dist, time = 80, 240, 3
check(Rational(dist, time) == speed and speed * time == dist and Rational(400, speed) == 5,
      "速さ＝道のり÷時間・道のり＝速さ×時間・時間＝道のり÷速さ（分速80m・3分・240m／400m・5分）")

print("4. 2軸の表（graph-1、qa.py は単位つき見出しを照合しない）")
mx = block("graph-1", "table")
minutes = [num(h) for h in mx["head"][1:]]
for row in mx["rows"]:
    cells = row["cells"]
    v = num(cells[0])
    for t, c in zip(minutes, cells[1:]):
        check(v * t == num(c), f"{cells[0]} × {t}分 = {c}m")
check(80 * 3 == 240, "graph-1 台詞：分速80mで3分 → 240m（強調するセル）")
check(num(mx["rows"][1]["cells"][3]) == 240 and mx["head"][3] == "3分", "強調するセル（分速80mの行 × 3分の列）が 240")
for v in (60, 80):
    check(all(v * (2 * t) == 2 * (v * t) and v * (3 * t) == 3 * (v * t) for t in range(1, 3)), f"分速{v}m：時間が2倍・3倍で道のりも2倍・3倍（比例）")

print("5. 折れ線（graph-2）")
ln = block("graph-2", "chart")
mins = [num(x) for x in ln["labels"]]
for s in ln["series"]:
    v = num(re.search(r"分速(\d+)m", s["name"]).group(1))
    check(s["values"] == [v * t for t in mins], f"{s['name']} の値 = 分速 × 時間")
check(ln["series"][1]["values"][-1] > ln["series"][0]["values"][-1], "B の線のほうが急（5分で 400 > 300）")

print("6. 傾き（graph-3）")
pl = block("graph-3", "plot")
line = pl["curves"][0]
check(line["kind"] == "line" and line["m"] == 4 and line["k"] == 0 and "時速4km" == line["label"], "直線 y = 4x（時速4km）")
segs = [c for c in pl["curves"] if c["kind"] == "segment"]
(x0, y0), (x1, y1) = segs[0]["from"], segs[0]["to"]
check(y0 == 4 * x0 and y0 == y1 and x1 - x0 == 1 and segs[0]["label"] == "1時間", "横の線分：直線上の点から右へ1（1時間）")
(x0, y0), (x1, y1) = segs[1]["from"], segs[1]["to"]
check(x0 == x1 and y1 - y0 == 4 and y1 == 4 * x1 and segs[1]["label"] == "4km", "縦の線分：上へ4（4km）で直線に戻る")
check(pl["y"][1] >= 4 * pl["x"][1], "3時間で12kmまで表示範囲に入る")

print("7. 換算表（units-1、qa.py は速さの単位を照合しない）")
cv = block("units-1", "table")
check(cv["head"] == ["時速", "分速", "秒速"], "列は 時速（km）・分速（m）・秒速（m）")
for row in cv["rows"]:
    h, m, s = (num(c) for c in row["cells"])
    check(h * KM / HOUR == m and m / MIN == s, f"時速{h}km = 分速{m}m = 秒速{s}m")
t = lines("units-1")
check(1 * MIN == 60 and 1 * MIN * HOUR == 3600 and Rational(3600, KM) == Rational(36, 10), "台詞：秒速1m → 1分で60m、1時間で3600m、時速3.6km")
check("1時間は60分、1分は60秒" in t, "台詞：1時間は60分、1分は60秒")

print("8. 問い")
q1 = block("check-1", "quiz")
d = Rational(12, 10) * KM
check(d == 1200 and d / 80 == 15, "check-1：1.2km = 1200m、1200 ÷ 80 = 15分")
check("15分" in q1["answer"] and "15分" in scenes["check-1"]["lines"][1]["text"], "check-1：画面の答えと台詞が 15分")
s8 = 8
m8 = s8 * MIN
h8 = m8 * HOUR
check(m8 == 480 and h8 == 28800 and Rational(h8, KM) == Rational(288, 10), "check-2：秒速8m = 分速480m = 時速28800m = 28.8km")
check(Rational(288, 10) < 30, "check-2：28.8 < 30 で、バスが速い")
q2 = block("check-2", "quiz")
check("28.8km" in q2["answer"] and "時速30kmのほうが速い" in q2["answer"], "check-2：画面の答えに 28.8km と「時速30kmのほうが速い」")

print("9. 速さの比較（台詞と画面の言い換え）")
check(b_speed * HOUR / KM == Rational(48, 10), "参考：分速80m = 時速4.8km（台本には出さない）")

print()
print(f"結果：OK {ok} 件・NG {ng} 件")
sys.exit(1 if ng else 0)
