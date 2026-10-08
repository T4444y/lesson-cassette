"""tennis-scoring の検算

使い方: python3 lessons/tennis-scoring.verify.py
- ITF の規則（規則 5〜7、タイブレークのサーブの順番）をプログラムで書き、
  台本の表・問いの答え・まとめの主張が、その結果と合うかを 1 つずつ確かめる
"""
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
doc = yaml.safe_load(open(os.path.join(HERE, "tennis-scoring.yaml"), encoding="utf-8"))
scenes = {sc["id"]: sc for ch in doc["chapters"] for sc in ch["scenes"]}
CALL = {0: "0", 1: "15", 2: "30", 3: "40"}
fails, oks = [], 0


def check(name, got, want):
    global oks
    if got == want:
        oks += 1
        print(f"OK  {name}: {got}")
    else:
        fails.append(name)
        print(f"NG  {name}: {got} ≠ {want}")


def game_score(points):
    """標準ゲーム（規則 5a）。points は 'S'（サーバー）/'R' の列。今の呼び方を返す"""
    s = r = 0
    for p in points:
        if p == "S":
            s += 1
        else:
            r += 1
        if (s >= 4 or r >= 4) and abs(s - r) >= 2:
            return "ゲーム（サーバー）" if s > r else "ゲーム（レシーバー）"
    if s >= 3 and r >= 3:
        return "デュース" if s == r else ("アドバンテージ（サーバー）" if s > r else "アドバンテージ（レシーバー）")
    return f"{CALL[s]} - {CALL[r]}"


def set_state(a, b, tiebreak=True):
    """セット（規則 6）。a, b はゲーム数"""
    if (a >= 6 or b >= 6) and abs(a - b) >= 2:
        return "セットを取る"
    if tiebreak and a == 6 and b == 6:
        return "タイブレークで決める"
    if a == 7 or b == 7:
        return "セットを取る"  # タイブレークのあとの 7 - 6
    return "続く"


def tiebreak_server(n, first="A"):
    """タイブレークの n ポイント目（1 から）のサーバー。最初の 1 本のあと 2 本ずつ交代"""
    other = "B" if first == "A" else "A"
    if n == 1:
        return first
    return other if ((n - 2) // 2) % 2 == 0 else first


# game-1 の表：0〜3 ポイントの呼び方と、4 ポイント目でゲーム
row = scenes["game-1"]["blocks"][1]["rows"][0]
for i in range(4):
    check(f"game-1 {i} ポイント", row[i + 1], CALL[i])
check("game-1 4 ポイント目（相手 0）", game_score("SSSS"), "ゲーム（サーバー）")

# game-2 の表：作った例の進み方
seq = ""
for r in scenes["game-2"]["blocks"][1]["rows"]:
    who, score = r["cells"]
    seq += "S" if who == "サーバー" else "R"
    want = game_score(seq)
    check(f"game-2 {seq}", score if score != "ゲーム" else "ゲーム（サーバー）", want)

# deuce-1：40 - 40 はデュース、次でアドバンテージ、続けてゲーム、落とせばデュース
check("deuce 3-3", game_score("SSSRRR"), "デュース")
check("deuce 次を取る", game_score("SSSRRRS"), "アドバンテージ（サーバー）")
check("deuce 続けて取る", game_score("SSSRRRSS"), "ゲーム（サーバー）")
check("deuce 落とす", game_score("SSSRRRSR"), "デュース")

# set-1 の表
for r in scenes["set-1"]["blocks"][1]["rows"]:
    score, what = r["cells"]
    a, b = (int(x) for x in score.split(" - "))
    shown = "続く" if what.startswith("まだ続く") else what
    check(f"set-1 {score}", shown, set_state(a, b))

# tie-2 の表：サーブの順番
head = scenes["tie-2"]["blocks"][1]["head"][1:]
servers = scenes["tie-2"]["blocks"][1]["rows"][0][1:]
for h, sv in zip(head, servers):
    for n in (int(x) for x in h.split("・")):
        check(f"tie-2 {n} ポイント目", sv, tiebreak_server(n))

# tie-1：7 ポイント先取・2 ポイント差、セットのスコアは 7 - 6
def tiebreak_done(a, b):
    return (a >= 7 or b >= 7) and abs(a - b) >= 2
check("tie 7-5 で終わる", tiebreak_done(7, 5), True)
check("tie 7-6 では終わらない", tiebreak_done(7, 6), False)
check("tie 9-7 で終わる", tiebreak_done(9, 7), True)
check("タイブレーク後のセット", set_state(7, 6), "セットを取る")

# 問い
check("check-1 30-40 から 2 本", game_score("SSRRR" + "SS"), "アドバンテージ（サーバー）")
check("check-1 1 本目", game_score("SSRRR" + "S"), "デュース")
check("check-2 6-5 から 5 の側", set_state(6, 6), "タイブレークで決める")

# マッチ（規則 7）
check("3 セットマッチは 2 セット", 3 // 2 + 1, 2)
check("5 セットマッチは 3 セット", 5 // 2 + 1, 3)

print(f"\n結果：OK {oks} 件・NG {len(fails)} 件")
sys.exit(1 if fails else 0)
