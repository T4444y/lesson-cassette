"""time-difference の検算（sympy の分数）

使い方: python3 lessons/time-difference.verify.py
- 経度と時刻の関係（360 度 ÷ 24 時間）から、台詞・画面・問いの答えにある数を 1 つずつ確かめる
- 標準時の基準（日本 東経135度・UTC+9、イギリス冬 0度・UTC+0、アメリカ東部冬 西経75度・UTC−5）は
  出典（NICT・Wikipedia）の値。ここでは、経度から求めた時差がそれと合うかを確かめる
"""
import os
import re
import sys

import yaml
from sympy import Rational as R

HERE = os.path.dirname(os.path.abspath(__file__))
doc = yaml.safe_load(open(os.path.join(HERE, "time-difference.yaml"), encoding="utf-8"))
scenes = {sc["id"]: sc for ch in doc["chapters"] for sc in ch["scenes"]}
fails, oks = [], 0
DEG_PER_HOUR = R(360, 24)


def check(name, got, want):
    global oks
    if got == want:
        oks += 1
        print(f"OK  {name}: {got}")
    else:
        fails.append(name)
        print(f"NG  {name}: {got} ≠ {want}")


# rot-1
check("rot-1 360 ÷ 24", DEG_PER_HOUR, 15)
check("rot-1 1 度は 60 ÷ 15 分", R(60) / DEG_PER_HOUR, 4)

# nl-1 の点：「9時間 = 135度」
nl = scenes["nl-1"]["blocks"][1]
check("nl-1 下の目盛りの倍率", R(nl["second"]["factor"]), DEG_PER_HOUR)
for p in nl["points"]:
    h, d = (R(x) for x in re.fullmatch(r"(\d+)時間 = (\d+)度", p["label"]).groups())
    check(f"nl-1 {p['label']}（位置）", R(p["value"]), h)
    check(f"nl-1 {p['label']}（度）", h * DEG_PER_HOUR, d)

# jst-1・zones-1：経度から求めた時差（東が＋、西が−）
ZONES = {"日本": (R(135), R(9)), "イギリス（冬）": (R(0), R(0)), "アメリカ東部（冬）": (R(-75), R(-5))}
for r in scenes["zones-1"]["blocks"][1]["rows"]:
    area, lon, diff = r["cells"]
    m = re.fullmatch(r"(東経|西経)?(\d+)度", lon)
    deg = R(m.group(2)) * (-1 if m.group(1) == "西経" else 1)
    shown = R(0) if diff == "±0" else R(diff.replace("＋", "").replace("−", "-").replace("時間", ""))
    check(f"zones-1 {area} の経度", deg, ZONES[area][0])
    check(f"zones-1 {area} 経度 ÷ 15", deg / DEG_PER_HOUR, shown)
    check(f"zones-1 {area} の時差（出典の値）", shown, ZONES[area][1])

# calc-1：数直線の点と帯
nl = scenes["calc-1"]["blocks"][1]
for p in nl["points"]:
    name = p["label"].split("（")[0]
    key = {"日本": "日本", "イギリス": "イギリス（冬）", "アメリカ東部": "アメリカ東部（冬）"}[name]
    check(f"calc-1 {name} の位置", R(p["value"]), ZONES[key][1])
sp = nl["spans"][0]
check("calc-1 日本とアメリカ東部の時差", R(sp["to"]) - R(sp["from"]), R(14))
check("calc-1 9 と 5 を足す", R(9) + R(5), R(14))

# 問い
check("check-1 午後3時（15時）から 9 時間戻す", (15 - 9) % 24, 6)
check("check-2 45 ÷ 15", R(45) / DEG_PER_HOUR, 3)

print(f"\n結果：OK {oks} 件・NG {len(fails)} 件")
sys.exit(1 if fails else 0)
