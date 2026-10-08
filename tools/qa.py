#!/usr/bin/env python3
"""台本・カセットの品質チェックを 1 コマンドで行う。

  python3 tools/qa.py lessons/my-topic.yaml                    # 台本（下書きを作り、画面まで確認）
  python3 tools/qa.py dist/my-topic.cassette.json              # ビルド済みカセット（実際の時刻で画面を確認）
  python3 tools/qa.py lessons/my-topic.yaml --frames vertex-1  # 指定したシーンを 1 行ごとに撮る

出力（qa/<id>/）
  report.md            報告。「要対応 → 要確認 → 読み → グラフと表 → 画面」の順
  sheet-<n>.png        全シーンの最後の行の画面を 12 枚ずつ並べた一覧
  frames-<scene>.png   --frames で指定したシーンの、1 行ごとの画面

チェックの中身
  1. 形式        tools/cassette.py と同じ検証。エラーがあればここで止まる
  2. 長さ        かな読みのモーラ数と読点の数から見積もる（誤差 ±3% 程度）。音声入りなら実際の長さ
  3. 読み        全行を Open JTalk のかな読みにして並べる（読み辞書を当てたあと）。
                 読まれない文字（記号・全角英字など）は要対応。英字・数字・読みが割れやすい語には印を付ける。
                 印がなくても、かなは全行を目で確かめること
  4. グラフと表  ラベルの式・座標・{a} などの差し込みが数値と合うか／点が曲線の上にあるか／
                 値の表の (x, y) がグラフや行の見出しの式と合うか。2 次関数は状態ごとに頂点・軸・切片・一般形を計算して載せる
  5. 画面        全シーンの全行で、部品が画面からはみ出していないか・スクリプトのエラーがないか
                 （Playwright と Chromium が必要。なければ飛ばし、そのことを報告に書く）

終了コード：要対応が 1 件でもあれば 1
"""
import argparse
import contextlib
import datetime
import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cassette  # noqa: E402
from build_cassette import apply_readings, build as build_cassette, load_readings  # noqa: E402

SEC_PER_MORA = 0.122     # Open JTalk の実測：1 モーラ（かな 1 字）あたりの秒数
SEC_PER_PAUSE = 0.51     # 読点・句点 1 つあたりの間
MAX_SECONDS = 600        # SPEC 7-5：1 本は 10 分以内
GOOD_SECONDS = 480       # AUTHORING 2：目安は 3〜8 分
SHEET_TILES = 12

# 読みが割れやすい語（正規表現 → 正しい候補）。含む行には印を付ける。★は実際に読み違えた語
RISKY = [
    (r"重要度", "じゅうようど ★たび と読んだ"), (r"一般形", "いっぱんけい ★がた と読んだ"),
    (r"(?<!絶対)(?<!数)(?<!価)(?<!均)(?<!大)(?<!小)(?<!似)(?<!定)(?<!期)(?<!初)(?<!閾)値", "あたい／ね ★値の表 を ねのひょう と読んだ"),
    (r"(?<![最午前直以今戦背])後(?![半者ろ])", "あと／ご／のち ★より後に を ご、x分後 を ぶんご と読んだ"),
    (r"[0-9０-９一二三四五六七八九十百]分の", "ぶんの ★八分の を はっぷん、2分の1 を にふんのいち と読む"), (r"拍子", "びょうし／ひょうし"),
    (r"下がり", "さがり ★右下がり を みぎしたがり と読む"), (r"(?<![勝正抱自])負(?![けか担債荷傷])", "ふ ★負なら を まけなら と読む"),
    (r"[一二三四五六七八九]つめ", "ふたつめ など ★二つめ を につめ と読む（「二つ目」と書く）"),
    (r"何で", "なんで／なにで ★何でしょう を なにでしょう と読む"), (r"使い口", "★つかいこう と読む"),
    (r"小仕事", "★しょうしごと と読む"), (r"他(?![人者社国方])", "ほか／た ★他の方法 を たのほうほう と読む"),
    (r"その後", "そのあと／そのご"), (r"行っ", "いっ／おこなっ"), (r"上手", "じょうず／うわて"), (r"下手", "へた／しもて"),
    (r"今日", "きょう／こんにち"), (r"明日", "あした／あす"), (r"一日", "いちにち／ついたち"), (r"人気", "にんき／ひとけ"),
    (r"大事", "だいじ／おおごと"), (r"生物", "せいぶつ／なまもの"), (r"最中", "さいちゅう／もなか"), (r"市場", "しじょう／いちば"),
    (r"工場", "こうじょう／こうば"), (r"辛い", "つらい／からい"), (r"開く", "ひらく／あく"), (r"空く", "あく／すく"),
    (r"表と裏", "おもてとうら ★ひょうとうら と読む"),
    (r"^(?=.*(?:[0-9０-９]割|歩合|[0-9０-９]厘)).*?(?P<w>(?<![0-9０-９.．])[0-9０-９]分)(?![の後間])", "ふん／ぶ（歩合）★歩合の 5分 を ごふん と読む（歩合なら say に 5ぶ）"),
    (r"何分(?!の)", "なんぷん／なにぶん ★何分かかる を なにぶん と読む（時間なら say に なんぷん）"),
    (r"(?<![0-9０-９一二三四五六七八九十百半何自気部区成多余随充存寸])分(?=[とがをはにのや、。・]|$)", "ぶん／ぶ ★分という字 を わけ と読む"),
    (r"(?<![0-9０-９第順単上下首地学品方各])位(?![置相])", "くらい／い ★小数の位 を しょうすうのい と読む"),
    (r"[7７]人", "ななにん（しちにん と読む）"), (r"(?<![一二三四五六七八九十0-9０-９])行の", "ぎょう／くだり ★行の見出し を くだり と読む"),
    (r"揃え", "そろえ ★文字の揃え を ぞろえ、列の揃え を そろいえ と読む"),
]
# 数字のあとに空白を置くと、助数詞を単独の語として読む（2024 年 → トシ、3 つ → ツ）
SPACED_COUNTER = re.compile(r"[0-9０-９]\s+[年月日時分秒週人個回本枚番歳度円倍割章節つ件点問行列階]")
# 台詞の中のかなの数。助詞や動詞として解析されると抑揚が崩れる
KANA_NUMS = {"ぜろ", "れい", "いち", "に", "さん", "よん", "し", "ご", "ろく", "なな", "しち", "はち", "きゅう", "く", "じゅう"}
# かな読みに出てきても問題のない文字（カタカナ・長音・区切り）
KANA_OK = re.compile(r"[ァ-ヴヵヶー、。，？！「」（）『』・：…—\s]")


# ---------------------------------------------------------------- helpers
def F(v):
    return Fraction(str(v))


def fmt_num(v):
    """プレイヤーの fmtNum と同じ（小数 1 桁に丸め、マイナスは −）。"""
    r = math.floor(float(v) * 10 + 0.5) / 10
    s = str(int(r)) if r == int(r) else str(r)
    return s.replace("-", "−")


def fmt_frac(v):
    v = Fraction(v)
    s = str(v.numerator) if v.denominator == 1 else f"{v.numerator}/{v.denominator}"
    return s.replace("-", "−")


def poly_str(a, b, c):
    """ax² + bx + c を「2x² − 4x + 3」の形に。"""
    out = []
    for coef, var in ((a, "x²"), (b, "x"), (c, "")):
        if coef == 0:
            continue
        mag = abs(coef)
        body = (fmt_frac(mag) if (mag != 1 or not var) else "") + var
        if not out:
            out.append(("−" if coef < 0 else "") + body)
        else:
            out.append(("− " if coef < 0 else "+ ") + body)
    return " ".join(out) or "0"


def parse_number(s):
    s = str(s).strip().replace("−", "-").replace("－", "-").replace("，", "").replace(",", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:/(\d+))?", s)
    if not m:
        return None
    v = F(m.group(1))
    return v / int(m.group(2)) if m.group(2) else v


_X = None


def parse_expr_x(s):
    """「2(x − 1)² + 3」のような式を sympy の式にする。読めなければ None。"""
    global _X
    try:
        import sympy
        from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application,
                                                parse_expr, standard_transformations)
    except ImportError:
        return None
    if _X is None:
        _X = sympy.Symbol("x")
    t = (s.replace("−", "-").replace("－", "-").replace("²", "**2").replace("³", "**3")
         .replace("·", "*").replace("×", "*").replace("ｘ", "x").replace("（", "(").replace("）", ")"))
    if not re.fullmatch(r"[0-9x\s.+\-*/()^]+", t):
        return None
    try:
        return parse_expr(t, transformations=standard_transformations + (implicit_multiplication_application, convert_xor),
                          local_dict={"x": _X})
    except Exception:
        return None


def iter_scenes(doc):
    for ch in doc["chapters"]:
        for sc in ch["scenes"]:
            yield ch, sc


def visible(o, idx):
    return (o.get("at") is None or idx >= o["at"]) and (o.get("out") is None or idx < o["out"])


# ---------------------------------------------------------------- 2. length
def estimate_seconds(doc, readings):
    """かな読みのモーラ数と読点の数から見積もる（7 本 270 行の実測から求めた係数。誤差は 1 本あたり ±3% 程度）。"""
    import pyopenjtalk
    tm = {**cassette.TIMING_DEFAULTS, **(doc.get("timing") or {})}
    t, prev = tm["lead_in"], None
    for _, sc in iter_scenes(doc):
        for i, ln in enumerate(sc["lines"]):
            if prev is not None:
                t += max(tm["gap"], tm["scene_gap"] if i == 0 else 0, tm["pause_gap"] if prev.get("pause") else 0)
            kana = pyopenjtalk.g2p(apply_readings(ln.get("say") or ln["text"], readings), kana=True)
            mora = len(re.sub(r"[、。，？！「」（）『』・：…—\s]", "", kana))
            pauses = len(re.findall(r"[、。，？！]", kana))
            t += max(1.0, SEC_PER_MORA * mora + SEC_PER_PAUSE * pauses - 0.05)
            prev = ln
    return t + 0.8


# ---------------------------------------------------------------- 3. readings
def check_readings(doc, readings):
    import pyopenjtalk
    letter = {}

    def spelled(word):  # 英単語を 1 文字ずつ読んだときのかな
        return "".join(letter.setdefault(ch, pyopenjtalk.g2p(ch, kana=True)) for ch in word.upper())

    rows, must, maybe, flagged, kana_num_lines = [], [], [], 0, []
    for _, sc in iter_scenes(doc):
        for i, ln in enumerate(sc["lines"]):
            where = f"{sc['id']}#{i}"
            say = apply_readings(ln.get("say") or ln["text"], readings)
            kana = pyopenjtalk.g2p(say, kana=True)
            marks = []
            silent = sorted(set(ch for ch in kana if not KANA_OK.match(ch)))
            if silent:
                marks.append("読まれない文字 " + " ".join(silent))
                must.append(f"読み {where}: 読まれない文字 {' '.join(silent)} があります（say で読みを書く）")
            for m in SPACED_COUNTER.finditer(say):
                marks.append(f"数字と助数詞の間の空白「{m.group(0)}」")
                must.append(f"読み {where}: 「{m.group(0)}」のように数字と助数詞の間に空白があると、助数詞を別の語として読みます（空白を消す）")
            for w in re.findall(r"[A-Za-z]{2,}", say):
                if w != w.upper() and pyopenjtalk.g2p(w, kana=True) == spelled(w):
                    marks.append(f"英単語「{w}」を 1 文字ずつ読む")
                    must.append(f"読み {where}: 英単語「{w}」が 1 文字ずつ読まれます（{spelled(w)}）。カタカナを say か readings.yaml に書く")
            hits = [f"{m.groupdict().get('w') or m.group(0)}（{note}）" for pat, note in RISKY for m in [re.search(pat, say)] if m]
            if hits:
                marks.append("語: " + "、".join(hits))
            # かなの数が、数としてではなく助詞・動詞などとして解析されている
            fs = pyopenjtalk.run_frontend(say)
            bad = [f["string"] for j, f in enumerate(fs)
                   if f["string"] in KANA_NUMS and f["pos"] != "名詞"
                   and (j == 0 or fs[j - 1]["string"] in ("、", "，", "。", "マイナス", "プラス"))]
            if bad:
                marks.append("かなの数が数として読まれない「" + "」「".join(bad) + "」")
                kana_num_lines.append(where)
            flagged += bool(marks)
            rows.append({"where": where, "text": ln["text"], "say": say if ln.get("say") or say != ln["text"] else None,
                         "kana": kana, "marks": marks})
    if kana_num_lines:
        maybe.append(f"読み: かなで書いた数が助詞・動詞として解析され、抑揚が崩れる行が {len(kana_num_lines)} 行（{'、'.join(kana_num_lines)}）。"
                     "say の数は数字で書く（例：マイナス、に → マイナス2）。助詞の「に」などを読点のあとに置いただけなら、そのままでよい")
    return rows, must, maybe, flagged


# ---------------------------------------------------------------- 4. plots and tables
PARAMS = ("a", "p", "q", "m", "k", "x")


def base_params(c):
    if c["kind"] == "quadratic":
        if "b" in c:
            a, b, cc = F(c["a"]), F(c["b"]), F(c["c"])
            return {"a": a, "b": b, "c": cc, "general": True, "p": -b / (2 * a), "q": cc - b * b / (4 * a)}
        return {"a": F(c["a"]), "p": F(c["p"]), "q": F(c["q"])}
    if c["kind"] == "line":
        return {"m": F(c["m"]), "k": F(c["k"])}
    if c["kind"] == "vline":
        return {"x": F(c["x"])}
    return {}


def params_at(c, idx):
    """行 idx を言い終えたあとの数値（動きの途中は見ない）。"""
    cur = base_params(c)
    for key in sorted(c.get("keys") or [], key=lambda k: k["at"]):
        if key["at"] > idx:
            break
        cur = dict(cur)
        for k in PARAMS:
            if k in key:
                cur[k] = F(key[k])
        if cur.get("general") and "a" in key:
            cur["p"], cur["q"] = -cur["b"] / (2 * cur["a"]), cur["c"] - cur["b"] ** 2 / (4 * cur["a"])
    return cur


def curve_states(curves, idx):
    st = [params_at(c, idx) for c in curves]
    for i, c in enumerate(curves):
        if c["kind"] == "axis":
            st[i] = {"x": st[c["of"]]["p"]}
    return st


def on_curve(c, prm, x, y):
    if c["kind"] == "quadratic":
        return prm["a"] * (x - prm["p"]) ** 2 + prm["q"] == y
    if c["kind"] == "line":
        return prm["m"] * x + prm["k"] == y
    return prm["x"] == x  # vline / axis


def curve_expr(c, prm):
    import sympy
    x = sympy.Symbol("x")
    if c["kind"] == "quadratic":
        return sympy.Rational(prm["a"]) * (x - sympy.Rational(prm["p"])) ** 2 + sympy.Rational(prm["q"])
    if c["kind"] == "line":
        return sympy.Rational(prm["m"]) * x + sympy.Rational(prm["k"])
    return None


def fill_template(s, prm):
    return re.sub(r"\{([apqmkx])\}", lambda m: fmt_num(prm[m.group(1)]) if m.group(1) in prm else m.group(0), str(s))


def check_label(label, where, kind_desc, prm, c, must, maybe):
    shown = fill_template(label, prm)
    left = re.findall(r"\{[^}]*\}", shown)
    if left:
        must.append(f"{where}: ラベル「{label}」の {' '.join(left)} は差し込めません（使えるのは {{a}} {{p}} {{q}} {{m}} {{k}} {{x}}）")
    for k in set(re.findall(r"\{([apqmkx])\}", str(label))):
        if k in prm and Fraction(prm[k]) * 10 != int(Fraction(prm[k]) * 10):
            maybe.append(f"{where}: ラベルの {{{k}}} = {fmt_frac(prm[k])} は小数 1 桁に丸めて「{fmt_num(prm[k])}」と表示されます")
    if c is not None and c["kind"] in ("quadratic", "line"):
        m = re.search(r"y\s*=\s*([0-9xｘ\s.+\-−－*/()（）²³^·×]+)", shown)
        if m:
            e = parse_expr_x(m.group(1).strip())
            if e is None:
                maybe.append(f"{where}: ラベル「{shown}」を式として読めず、数値と照合できませんでした")
            else:
                import sympy
                if sympy.simplify(sympy.expand(e - curve_expr(c, prm))) != 0:
                    must.append(f"{where}: ラベル「{shown}」が {kind_desc}（y = {curve_text(c, prm)}）と合いません")
    if c is not None and c["kind"] in ("vline", "axis"):
        m = re.search(r"x\s*=\s*(−?-?\d+(?:\.\d+)?(?:/\d+)?)", shown)
        if m and parse_number(m.group(1)) != prm["x"]:
            must.append(f"{where}: ラベル「{shown}」が線の位置 x = {fmt_frac(prm['x'])} と合いません")
    return shown


def curve_text(c, prm):
    if c["kind"] == "quadratic":
        a, p, q = prm["a"], prm["p"], prm["q"]
        return poly_str(a, -2 * a * p, a * p * p + q)
    if c["kind"] == "line":
        return poly_str(0, prm["m"], prm["k"])
    return f"x = {fmt_frac(prm['x'])}"


def quad_facts(prm):
    a, p, q = prm["a"], prm["p"], prm["q"]
    b, c = -2 * a * p, a * p * p + q
    r = -q / a
    if r < 0:
        roots = "なし"
    elif r == 0:
        roots = fmt_frac(p)
    else:
        import sympy
        s = sympy.sqrt(sympy.Rational(r))
        roots = "、".join(str(sympy.nsimplify(sympy.Rational(p) + sg * s)).replace("sqrt", "√").replace("-", "−") for sg in (-1, 1))
    return {"一般形": f"y = {poly_str(a, b, c)}", "頂点": f"({fmt_frac(p)}, {fmt_frac(q)})", "軸": f"x = {fmt_frac(p)}",
            "y 切片": fmt_frac(c), "x 切片": roots, "向き": "下に凸" if a > 0 else "上に凸"}


def check_graphs(doc):
    must, maybe, facts, lines_facts = [], [], [], []
    count = {"ラベル": 0, "点の位置": 0, "値の表の組": 0}
    for _, sc in iter_scenes(doc):
        n = len(sc["lines"])
        plots = [(bi, b) for bi, b in enumerate(sc["blocks"]) if b.get("type") == "plot"]
        for bi, b in plots:
            curves, points = b.get("curves") or [], b.get("points") or []
            base = f"{sc['id']} plot[{bi}]"
            # facts table (each distinct state of each quadratic)
            for ci, c in enumerate(curves):
                if c["kind"] not in ("quadratic", "line"):
                    continue
                seen = []
                for idx in range(n):
                    prm = params_at(c, idx)
                    sig = tuple(sorted((k, v) for k, v in prm.items() if k in PARAMS))
                    if sig in seen:
                        continue
                    seen.append(sig)
                    if c["kind"] == "quadratic":
                        facts.append({"where": f"{base} 曲線{ci}", "from": idx, **quad_facts(prm)})
                    else:
                        lines_facts.append({"where": f"{base} 曲線{ci}", "from": idx, **line_facts(prm)})
            # labels and points, line by line (a label is checked again only when its text changes)
            reported, last_shown = set(), {}
            for idx in range(n):
                st = curve_states(curves, idx)
                for ci, c in enumerate(curves):
                    if c.get("label") and visible(c, idx):
                        shown = fill_template(c["label"], st[ci])
                        if last_shown.get(("c", ci)) != shown:
                            last_shown[("c", ci)] = shown
                            check_label(c["label"], f"{base} 曲線{ci} 行{idx}", "曲線", st[ci], c, must, maybe)
                            count["ラベル"] += 1
                for pi, pt in enumerate(points):
                    if not visible(pt, idx):
                        continue
                    if "vertex_of" in pt:
                        v = st[pt["vertex_of"]]
                        x, y, prm = v["p"], v["q"], {**v, "x": v["p"]}
                    else:
                        x, y, prm = F(pt["x"]), F(pt["y"]), {"x": F(pt["x"])}
                    where = f"{base} 点{pi} 行{idx}"
                    if pt.get("label") and last_shown.get(("p", pi)) != fill_template(pt["label"], prm):
                        last_shown[("p", pi)] = fill_template(pt["label"], prm)
                        shown = check_label(pt["label"], where, "点", prm, None, must, maybe)
                        count["ラベル"] += 1
                        m = re.search(r"[(（]\s*(−?-?[\d./]+)\s*[,，、]\s*(−?-?[\d./]+)\s*[)）]", shown)
                        if m and (parse_number(m.group(1)), parse_number(m.group(2))) != (x, y):
                            must.append(f"{where}: ラベル「{shown}」が点の位置 ({fmt_frac(x)}, {fmt_frac(y)}) と合いません")
                    if "vertex_of" not in pt and curves and ("off", pi) not in reported and ("ok", pi) not in reported:
                        # 点は「そのシーンのどこかで表示される線」のどれかに乗っていればよい（線より先に点を打つ演出があるため）
                        ok = any(visible(c, j) and on_curve(c, curve_states(curves, j)[ci], x, y)
                                 for j in range(n) for ci, c in enumerate(curves))
                        reported.add(("ok", pi))
                        count["点の位置"] += 1
                        if not ok:
                            reported.add(("off", pi))
                            maybe.append(f"{base} 点{pi} ({fmt_frac(x)}, {fmt_frac(y)}): このシーンのどの線の上にもありません（意図どおりか確認）")
        # value tables
        for bi, b in enumerate(sc["blocks"]):
            if b.get("type") != "table":
                continue
            head = [str(h) for h in b.get("head") or []]
            if not head or head[0].strip().lower() not in ("x", "ｘ"):
                continue
            xs = [parse_number(h) for h in head[1:]]
            for ri, row in enumerate(b.get("rows") or []):
                cells = row.get("cells") if isinstance(row, dict) else row
                if not cells:
                    continue
                lab = str(cells[0]).strip()
                where = f"{sc['id']} table[{bi}] 行{ri}「{lab}」"
                ys = [parse_number(cv) for cv in cells[1:]]
                pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
                rhs = re.sub(r"^\s*y\s*=\s*", "", lab)
                e = parse_expr_x(rhs) if lab.lower() not in ("y", "ｙ") else None
                if e is not None:
                    import sympy
                    bad = [(x, y) for x, y in pairs if sympy.Rational(y) != e.subs(sympy.Symbol("x"), sympy.Rational(x))]
                    count["値の表の組"] += len(pairs)
                    for x, y in bad:
                        must.append(f"{where}: x = {fmt_frac(x)} のとき {lab} は {fmt_frac(Fraction(str(e.subs(sympy.Symbol('x'), sympy.Rational(x)))))} ですが、表は {fmt_frac(y)} です")
                    continue
                if not plots:
                    maybe.append(f"{where}: 同じシーンにグラフがないため値を照合していません（sympy で検算すること）")
                    continue
                cands = []
                for _, pb in plots:
                    pcs = pb.get("curves") or []
                    for idx in range(n):
                        st = curve_states(pcs, idx)
                        cands += [(c, st[ci]) for ci, c in enumerate(pcs) if c["kind"] in ("quadratic", "line")]
                    cands += [("pt", (F(p["x"]), F(p["y"]))) for p in pb.get("points") or [] if "x" in p]
                count["値の表の組"] += len(pairs)
                for x, y in pairs:
                    if not any((c == "pt" and prm == (x, y)) or (c != "pt" and on_curve(c, prm, x, y)) for c, prm in cands):
                        maybe.append(f"{where}: (x, y) = ({fmt_frac(x)}, {fmt_frac(y)}) が、このシーンのグラフのどの線・点とも合いません")
    return must, maybe, facts, lines_facts, count


# 単位：(種類, 基準の単位あたりの大きさ)。長さは m、重さは g、かさは L、時間は秒、速さは秒速 m
UNITS = {"km": ("長さ", 1000), "m": ("長さ", 1), "cm": ("長さ", Fraction(1, 100)), "mm": ("長さ", Fraction(1, 1000)),
         "t": ("重さ", 10 ** 6), "kg": ("重さ", 1000), "g": ("重さ", 1), "mg": ("重さ", Fraction(1, 1000)),
         "kL": ("かさ", 1000), "L": ("かさ", 1), "dL": ("かさ", Fraction(1, 10)), "mL": ("かさ", Fraction(1, 1000)),
         "日": ("時間", 86400), "時間": ("時間", 3600), "分": ("時間", 60), "秒": ("時間", 1)}
SPEED_PER = {"時速": 3600, "分速": 60, "秒速": 1}
NUM = r"(-?\d+(?:\.\d+)?(?:/\d+)?)"


def _clean(s):
    return (str(s).strip().replace("−", "-").replace("－", "-").replace("，", "").replace(",", "")
            .replace("ｍ", "m").replace("ｋ", "k").replace("ｃ", "c").replace("ｇ", "g").replace("Ｌ", "L").replace(" ", "").replace("　", ""))


def head_unit(h):
    """見出しの単位：「km」「時間」「百分率（%）」「分速（m）」など。なければ None。"""
    t = _clean(h)
    m = re.fullmatch(r"(.*?)[（(]([^（）()]+)[）)]", t)
    name, u = (m.group(1), m.group(2)) if m else ("", t)
    sp = next((k for k in SPEED_PER if (name or t).startswith(k)), None)
    if sp:  # 「時速」「分速（m）」：セルの長さを、その時間あたりの速さとして読む
        return (sp, u if u in UNITS and UNITS[u][0] == "長さ" else None)
    if u in UNITS or u in ("%", "％", "割"):
        return u
    return None


def parse_quantity(cell, unit=None):
    """セルを (種類, 基準の単位での大きさ) の候補の集合にする。読めなければ空。
    数だけのセルは、見出しの単位（unit）があればそれで読む。「5分」は、時間（5 分間）と歩合（0.05）の両方を候補にする。"""
    t = _clean(cell)
    out = set()
    v = parse_number(t)
    if v is not None:
        if unit is None:
            out.add(("数", v))
        elif isinstance(unit, tuple):
            if unit[1]:
                out.add(("速さ", v * UNITS[unit[1]][1] / SPEED_PER[unit[0]]))
        elif unit in ("%", "％"):
            out.add(("数", v / 100))
        elif unit == "割":
            out.add(("数", v / 10))
        else:
            kind, f = UNITS[unit]
            out.add((kind, v * f))
        return out
    m = re.fullmatch(NUM + r"[%％]", t)
    if m:
        return {("数", parse_number(m.group(1)) / 100)}
    m = re.fullmatch(r"(?:(\d+)割)?(?:(\d+)分)?(?:(\d+)厘)?", t)
    if m and any(m.groups()):
        a, b, c = (int(g or 0) for g in m.groups())
        out.add(("数", Fraction(a, 10) + Fraction(b, 100) + Fraction(c, 1000)))
    m = re.fullmatch(r"(時速|分速|秒速)" + NUM + r"(km|m|cm|mm)", t)
    if m:
        out.add(("速さ", parse_number(m.group(2)) * UNITS[m.group(3)][1] / SPEED_PER[m.group(1)]))
    m = re.fullmatch(NUM + r"(km|cm|mm|m|kg|mg|g|t|kL|dL|mL|L)", t)
    if m:
        kind, f = UNITS[m.group(2)]
        if isinstance(unit, tuple) and kind == "長さ":  # 見出しが「時速」なら、36km は時速 36km
            out.add(("速さ", parse_number(m.group(1)) * f / SPEED_PER[unit[0]]))
        else:
            out.add((kind, parse_number(m.group(1)) * f))
    parts = re.findall(NUM + r"(日|時間|分|秒)", t)
    if parts and "".join(n + u for n, u in parts) == t:
        out.add(("時間", sum(parse_number(n) * UNITS[u][1] for n, u in parts)))
    return out


def lead_number(s):
    """「分速80m」「1分」「4km」の最初の数。なければ None。"""
    m = re.search(NUM, _clean(s))
    return parse_number(m.group(1)) if m else None


def parse_amount(s):
    """換算表のセルを数にする：0.25・1/4・25%・2割5分（歩合）。読めなければ None。"""
    c = sorted(v for k, v in parse_quantity(s) if k == "数")
    return c[0] if c else None


def check_tables_more(doc):
    """2 軸の表（角が × か ＋）の計算と、換算表の各行が同じ大きさかを確かめる。照合できなかった表・行は要確認にする。"""
    must, maybe, count = [], [], 0
    for _, sc in iter_scenes(doc):
        for bi, b in enumerate(sc["blocks"]):
            if b.get("type") != "table":
                continue
            rows = [r.get("cells") if isinstance(r, dict) else r for r in b.get("rows") or []]
            where = f"{sc['id']} table[{bi}]"
            if b.get("style") == "matrix" and str(b["head"][0]).strip() in ("×", "x", "*", "+", "＋"):
                op = str(b["head"][0]).strip()
                add = op in ("+", "＋")
                skipped = []
                for r in rows:
                    for ch, cell in zip(b["head"][1:], r[1:]):
                        a, c, v = (parse_quantity(x) for x in (r[0], ch, cell))
                        pa, pc, pv = (lead_number(x) for x in (r[0], ch, cell))
                        if None in (pa, pc, pv):
                            skipped.append(str(cell))
                            continue
                        count += 1
                        plain = all(any(k == "数" for k, _ in q) for q in (a, c, v))
                        if not add:  # 速さ × 時間 = 道のり は、単位をそろえて計算する
                            hit = None
                            for (ka, va) in a:
                                for (kc, vc) in c:
                                    if {ka, kc} == {"速さ", "時間"}:
                                        hit = va * vc
                            lens = [vv for kk, vv in v if kk == "長さ"]
                            if hit is not None and not lens and parse_number(cell) is not None:  # 単位のないセルは、速さの長さの単位で読む
                                f = next((UNITS[mm.group(2)][1] for x in (r[0], ch) for mm in [re.search(r"(?:時速|分速|秒速)" + NUM + r"(km|m|cm|mm)", _clean(x))] if mm), None)
                                lens = [pv * f] if f is not None else []
                            if hit is not None and lens:
                                if hit != lens[0]:
                                    must.append(f"{where}: {r[0]} × {ch} は {fmt_frac(hit)}m ですが、表は {cell} です")
                                continue
                        want = pa + pc if add else pa * pc
                        if pv == want:
                            continue
                        if plain:
                            must.append(f"{where}: {fmt_frac(pa)} {op} {fmt_frac(pc)} は {fmt_frac(want)} ですが、表は {cell} です")
                        else:
                            maybe.append(f"{where}: 「{r[0]}」{op}「{ch}」を数だけで計算すると {fmt_frac(want)} ですが、表は「{cell}」です（単位の換算があれば問題ありません）")
                if skipped:
                    maybe.append(f"{where}: 数の読めないセルが {len(skipped)} 個あり、計算を照合していません（{'・'.join(skipped[:4])}）")
            if b.get("style") == "convert":
                units = [head_unit(h) for h in b["head"]]
                for ri, r in enumerate(rows):
                    cands = [parse_quantity(cell, u) for cell, u in zip(r, units)]
                    unread = [str(c) for c, q in zip(r, cands) if not q and str(c).strip()]
                    kinds = set.intersection(*[{k for k, _ in q} for q in cands if q]) if any(cands) else set()
                    read = [q for q in cands if q]
                    if unread or len(read) < 2 or not kinds:
                        why = (f"「{'」「'.join(unread)}」を数として読めない" if unread
                               else "量の種類（長さ・時間・速さ・数など）がそろわない" if len(read) >= 2 else "数として読めるセルが 1 つ以下")
                        maybe.append(f"{where} 行{ri}: {why}ため、同じ大きさかを照合していません（単位はセルか見出しの括弧に書く。AUTHORING 3）")
                        continue
                    kind = "数" if "数" in kinds else sorted(kinds)[0]
                    vals = [(cell, next(v for k, v in sorted(q) if k == kind)) for cell, q in zip(r, cands) if q]
                    count += 1
                    if len({v for _, v in vals}) > 1:
                        unit = {"数": "", "長さ": "m", "重さ": "g", "かさ": "L", "時間": "秒", "速さ": "m/秒"}[kind]
                        must.append(f"{where} 行{ri}: 同じ大きさになっていません（{'・'.join(f'{c} = {fmt_frac(v)}{unit}' for c, v in vals)}）")
    for _, sc in iter_scenes(doc):
        for bi, b in enumerate(sc["blocks"]):
            if b.get("type") != "numberline":
                continue
            sec = b.get("second") or {}
            suf, ssuf, pre = b.get("suffix") or "", sec.get("suffix") or "", sec.get("prefix") or ""
            fac = F(sec.get("factor", 1))
            for pi, pt in enumerate(b.get("points") or []):
                if pt.get("label") is None:
                    continue
                v = F(pt["value"])
                label = str(pt["label"])
                checks = []  # (書かれた部分, 読んだ数, 上の目盛りか)
                for part in re.split(r"[=＝]", label):
                    part = part.strip()
                    main = parse_number(part.removesuffix(suf)) if suf else parse_number(part)
                    other = parse_number(part.removesuffix(ssuf).removeprefix(pre)) if ssuf and part.endswith(ssuf) else None
                    if main is not None or other is not None:
                        checks.append((part, main, other))
                if not checks:  # 「4分で300m」のように = のない書き方：単位のついた数を拾う
                    for sfx, top in ((suf, True), (ssuf, False)):
                        if not sfx:
                            continue
                        for mm in re.finditer(re.escape(pre if not top else "") + NUM + re.escape(sfx) + r"(?![A-Za-zａ-ｚ])", label):
                            n = parse_number(mm.group(1))
                            checks.append((mm.group(0), n if top else None, None if top else n))
                for part, main, other in checks:
                    count += 1
                    ok = (main is not None and main == v) or (other is not None and other == v * fac)
                    if not ok:
                        must.append(f"{sc['id']} numberline[{bi}] 点{pi}: ラベル「{label}」の「{part}」が点の位置 {fmt_frac(v)} と合いません")
    return must, maybe, count


def chart_facts(doc):
    out = []
    for _, sc in iter_scenes(doc):
        for bi, b in enumerate(sc["blocks"]):
            if b.get("type") != "chart":
                continue
            for se in b.get("series") or []:
                vals = se.get("values") or []
                if not vals:
                    continue
                hi, lo = max(vals), min(vals)
                out.append({"where": f"{sc['id']} chart[{bi}]", "name": se.get("name", ""), "values": "・".join(f"{l}:{v}" for l, v in zip(b["labels"], vals)),
                            "max": f"{hi}（{'・'.join(str(l) for l, v in zip(b['labels'], vals) if v == hi)}）",
                            "min": f"{lo}（{'・'.join(str(l) for l, v in zip(b['labels'], vals) if v == lo)}）"})
    return out


def line_facts(prm):
    m, k = prm["m"], prm["k"]
    return {"式": f"y = {poly_str(0, m, k)}", "傾き": fmt_frac(m), "y 切片": fmt_frac(k),
            "x 切片": fmt_frac(-k / m) if m != 0 else "なし", "向き": "右上がり" if m > 0 else "右下がり" if m < 0 else "水平"}


# ---------------------------------------------------------------- 4b. keys that SPEC does not define
KNOWN = {
    "top": {"format", "version", "id", "title", "kicker", "lang", "sources", "timing", "chapters", "audio", "duration", "build"},
    "source": {"id", "label", "url", "note"}, "timing": set(cassette.TIMING_DEFAULTS),
    "chapter": {"id", "title", "scenes"}, "scene": {"id", "kind", "sources", "blocks", "lines"},
    "line": {"text", "say", "pause", "chunks", "start", "end"},
    "title": {"text", "kicker"}, "text": {"text"}, "bullets": {"items"}, "steps": {"items"}, "compare": {"left", "right", "arrow"},
    "formula": {"text"}, "code": {"code", "lang"}, "table": {"head", "rows", "cols", "style", "align", "widths"}, "note": {"text", "label"},
    "quiz": {"question", "answer", "answer_at"}, "plot": {"x", "y", "height", "curves", "points"},
    "bullet": {"text", "at", "out", "focus"}, "step": {"title", "note", "at", "out", "focus"}, "side": {"label", "title", "note", "tone"},
    "row": {"cells", "at", "out", "focus"}, "col": {"at", "out", "focus"},
    "curve": {"kind", "a", "p", "q", "b", "c", "m", "k", "x", "of", "keys", "color", "label", "at", "out", "from", "to", "arrow", "dash"},
    "key": {"at", "a", "p", "q", "m", "k", "x"}, "point": {"x", "y", "vertex_of", "label", "at", "out", "focus"},
    "numberline": {"range", "step", "label_every", "name", "suffix", "second", "points", "spans", "labels"},
    "nl_second": {"factor", "suffix", "prefix", "name"}, "nl_point": {"value", "label", "at", "out", "focus"},
    "nl_span": {"from", "to", "label", "at", "out", "focus"}, "nl_label": {"value", "text"},
    "chart": {"kind", "labels", "series", "y", "unit", "height", "values"}, "series": {"name", "values", "at", "out", "focus"},
}
TIMED = {"at", "out", "focus"}


def check_keys(doc):
    """SPEC にないキーは、プレイヤーが黙って無視する。書き手の意図が画面に出ないので要対応にする。"""
    bad = []

    def chk(o, kind, where):
        if isinstance(o, dict):
            extra = sorted(set(o) - KNOWN[kind])
            if extra:
                bad.append(f"キー {where}: SPEC にないキー {', '.join(extra)}（プレイヤーは無視する）")

    chk(doc, "top", "全体")
    for i, s in enumerate(doc.get("sources") or []):
        chk(s, "source", f"sources[{i}]")
    chk(doc.get("timing"), "timing", "timing")
    for ch, sc in iter_scenes(doc):
        chk(ch, "chapter", f"章 {ch['id']}")
        chk(sc, "scene", sc["id"])
        for i, ln in enumerate(sc["lines"]):
            chk(ln, "line", f"{sc['id']}#{i}")
        for bi, b in enumerate(sc["blocks"]):
            t, w = b.get("type"), f"{sc['id']} {b.get('type')}[{bi}]"
            if t in KNOWN:
                extra = sorted(set(b) - KNOWN[t] - TIMED - {"type"})
                if extra:
                    bad.append(f"キー {w}: SPEC にないキー {', '.join(extra)}（プレイヤーは無視する）")
            for j, it in enumerate(b.get("items") or []):
                chk(it, "bullet" if t == "bullets" else "step", f"{w}.items[{j}]")
            for side in ("left", "right"):
                if t == "compare":
                    chk(b.get(side), "side", f"{w}.{side}")
            for j, r in enumerate(b.get("rows") or []):
                chk(r, "row", f"{w}.rows[{j}]")
            for j, c in enumerate(b.get("cols") or []):
                chk(c, "col", f"{w}.cols[{j}]")
            for j, c in enumerate(b.get("curves") or []):
                chk(c, "curve", f"{w}.curves[{j}]")
                for kk, key in enumerate(c.get("keys") or [] if isinstance(c, dict) else []):
                    chk(key, "key", f"{w}.curves[{j}].keys[{kk}]")
            for j, pt in enumerate(b.get("points") or []):
                chk(pt, "nl_point" if t == "numberline" else "point", f"{w}.points[{j}]")
            if t == "numberline":
                chk(b.get("second"), "nl_second", f"{w}.second")
                for j, sp in enumerate(b.get("spans") or []):
                    chk(sp, "nl_span", f"{w}.spans[{j}]")
                for j, lb in enumerate(b.get("labels") or []):
                    chk(lb, "nl_label", f"{w}.labels[{j}]")
            if t == "chart":
                for j, se in enumerate(b.get("series") or []):
                    chk(se, "series", f"{w}.series[{j}]")
    return bad


def check_focus(doc):
    """箇条書き・手順で、focus を付けた項目と付けていない項目が混ざると、付けていない項目だけ明るく残る。"""
    out = []
    for _, sc in iter_scenes(doc):
        for bi, b in enumerate(sc["blocks"]):
            items = [it for it in b.get("items") or [] if b.get("type") in ("bullets", "steps")]
            with_f = [isinstance(it, dict) and "focus" in it for it in items]
            if any(with_f) and not all(with_f):
                out.append(f"{sc['id']} {b['type']}[{bi}]: focus のある項目とない項目が混ざっています（ない項目だけ明るく残る。全項目に付ける）")
    return out


def quiz_pairs(doc):
    out = []
    for _, sc in iter_scenes(doc):
        if sc.get("kind") != "quiz":
            continue
        for b in sc["blocks"]:
            if b.get("type") == "quiz":
                ai = b.get("answer_at", 1)
                out.append({"where": sc["id"], "q": b["question"], "a": b["answer"],
                            "line": sc["lines"][ai]["text"] if ai < len(sc["lines"]) else "（行がない）"})
    return out


# ---------------------------------------------------------------- 5. screen
OVERFLOW_JS = """() => {
  const sc = document.querySelector('.scene.active'); if (!sc) return ['表示中のシーンがありません'];
  const sr = sc.getBoundingClientRect(), out = [], hit = [];
  const name = (e) => `${e.tagName.toLowerCase()}「${(e.textContent || '').trim().slice(0, 20)}」`;
  for (const e of sc.querySelectorAll('*')) {
    if (e.closest('svg') && e.tagName.toLowerCase() !== 'svg') continue;
    if (hit.some((h) => h.contains(e))) continue;  // report only the outermost element
    const r = e.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || +cs.opacity === 0) continue;
    const d = { 上: sr.top - r.top, 下: r.bottom - sr.bottom, 左: sr.left - r.left, 右: r.right - sr.right };
    const sides = Object.entries(d).filter(([, v]) => v > 1).map(([k, v]) => `${k}に ${Math.round(v)}px`);
    if (sides.length) { hit.push(e); out.push(`${name(e)}が画面の${sides.join('・')} はみ出し`); continue; }
    if (e.scrollWidth > e.clientWidth + 2 && cs.overflow === 'hidden') { hit.push(e); out.push(`${name(e)}の中身が横に切れる`); continue; }
    if (/^T[DH]$/.test(e.tagName) && e.scrollWidth > e.clientWidth + 1) { hit.push(e); out.push(`表のセル${name(e)}が列の幅に収まらない（${e.scrollWidth - e.clientWidth}px）`); }
  }
  return out; }"""


# 見た目の崩れ（要確認）：グラフのラベルが線・点に重なる／式が折り返す／最後の行が 3 文字以下
LOOK_JS = """() => {
  const sc = document.querySelector('.scene.active'); if (!sc) return [];
  const out = [];
  const hidden = (e) => { for (let n = e; n && n !== sc; n = n.parentElement) {
    if ((n.dataset && n.dataset.at != null && !n.classList.contains('on')) || n.classList.contains('gone')) return true; } return false; };
  // graph labels vs lines and dots (SVG user units)
  for (const svg of sc.querySelectorAll('svg.b-plot')) {
    if (hidden(svg)) continue;
    const cr = svg.querySelector('clipPath rect'); if (!cr) continue;
    const bx = +cr.getAttribute('x'), by = +cr.getAttribute('y'), bw = +cr.getAttribute('width'), bh = +cr.getAttribute('height');
    const vis = (g) => !hidden(g);
    const labels = [...svg.querySelectorAll('g.pl-curve > text, g.pl-pt > text')].filter((t) => vis(t.parentNode) && t.textContent.trim());
    const paths = [...svg.querySelectorAll('g.pl-curve > path')].filter((p) => vis(p.parentNode));
    const dots = [...svg.querySelectorAll('g.pl-pt > circle')].filter((c) => vis(c.parentNode));
    for (const t of labels) {
      const b = t.getBBox(), m = 2;  // the text box has padding above and below the glyphs
      const inside = (x, y, pad) => x > b.x - pad && x < b.x + b.width + pad && y > b.y - pad && y < b.y + b.height + pad;
      for (const p of paths) {
        const L = p.getTotalLength();
        for (let s = 0; s <= L; s += 2) { const q = p.getPointAtLength(s);
          if (q.x < bx || q.x > bx + bw || q.y < by || q.y > by + bh) continue;
          if (inside(q.x, q.y, -m)) { const own = p.parentNode === t.parentNode;
            out.push({ key: 'lab-line:' + t.textContent + (own ? ':own' : ''), msg: `グラフのラベル「${t.textContent}」が${own ? '自分の' : 'ほかの'}線に重なる` }); break; } }
      }
      for (const c of dots) { if (c.parentNode === t.parentNode) continue;
        if (inside(+c.getAttribute('cx'), +c.getAttribute('cy'), 6)) out.push({ key: 'lab-dot:' + t.textContent, msg: `グラフのラベル「${t.textContent}」が点に重なる` }); }
    }
  }
  // number lines, charts and graphs: labels overlapping each other, or running past the drawing
  for (const svg of sc.querySelectorAll('svg.b-nl, svg.b-chart, svg.b-plot')) {
    if (hidden(svg)) continue;
    const [, , W, H] = svg.getAttribute('viewBox').split(' ').map(Number);
    const ts = [...svg.querySelectorAll('text')].filter((t) => !hidden(t) && t.textContent.trim()).map((t) => ({ s: t.textContent.trim(), b: t.getBBox() }));
    for (let i = 0; i < ts.length; i++) {
      const a = ts[i].b, s = ts[i].s;
      const side = a.x < -1 ? '左' : a.x + a.width > W + 1 ? '右' : a.y < -1 ? '上' : a.y + a.height > H + 1 ? '下' : null;
      if (side) out.push({ key: 'edge:' + s, msg: `図の文字「${s}」が図の${side}端からはみ出す` });
      for (let j = i + 1; j < ts.length; j++) { const b = ts[j].b, m = 2;
        if (a.x + m < b.x + b.width && b.x + m < a.x + a.width && a.y + m < b.y + b.height && b.y + m < a.y + a.height)
          out.push({ key: 'lab-lab:' + s + '|' + ts[j].s, msg: `図の文字「${s}」と「${ts[j].s}」が重なる` }); }
    }
  }
  // text wrapping: lines per element from the text fragments' boxes
  const lineInfo = (e) => { const fs = parseFloat(getComputedStyle(e).fontSize), lines = [];
    const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); const r = document.createRange();
    for (let n = w.nextNode(); n; n = w.nextNode()) { if (!n.textContent.trim() || n.parentElement.closest('svg')) continue; r.selectNodeContents(n);
      for (const x of r.getClientRects()) { if (x.width < 0.5) continue; const L = lines.find((l) => Math.abs(l.top - x.top) < fs * 0.5); if (L) L.w += x.width; else lines.push({ top: x.top, w: x.width }); } }
    lines.sort((a, b) => a.top - b.top); return { n: lines.length, last: lines.length ? lines[lines.length - 1].w : 0, fs }; };
  for (const e of sc.querySelectorAll('.formula')) { if (hidden(e)) continue; const li = lineInfo(e);
    if (li.n > 1) out.push({ key: 'wrap:' + e.textContent, msg: `式「${e.textContent.slice(0, 24)}」が ${li.n} 行に折り返す（formula は全角 11 字・半角 20 字程度まで）` }); }
  for (const e of sc.querySelectorAll('h2, p, li, b, small, td, th')) { if (hidden(e) || e.closest('svg')) continue;
    const li = lineInfo(e); if (li.n > 1 && li.last < li.fs * 3.2) out.push({ key: 'widow:' + e.textContent, msg: `「${e.textContent.trim().slice(0, 24)}」の最後の行が 3 文字以下（文を短くするか言い換える）` }); }
  return out; }"""


def check_screen(cassette_path, outdir, frames):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright がないため、画面チェックを飛ばしました（pip install playwright と Chromium が必要）"
    from PIL import Image
    tmp = tempfile.mkdtemp(prefix="qa-player-")
    subprocess.run([sys.executable, os.path.join(HERE, "build_player.py"), "--out", tmp], check=True, capture_output=True)
    player = os.path.join(tmp, "player.html")
    result = {"overflow": [], "look": [], "errors": [], "sheets": [], "frames": [], "alert": None}
    seen_look = set()
    tiles, frame_tiles = [], {s: [] for s in frames}
    with sync_playwright() as p:
        browser = None
        for exe in (None, os.environ.get("CHROMIUM_PATH")):
            try:
                browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
                break
            except Exception as e:  # noqa: BLE001
                why = str(e).splitlines()[0]
        if browser is None:
            return None, f"Chromium を起動できないため、画面チェックを飛ばしました（{why}）"
        ctx = browser.new_context(viewport={"width": 1000, "height": 900}, color_scheme="light")
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: result["errors"].append(str(e)))
        pg.goto("file://" + player)
        pg.set_input_files("#fileIn", cassette_path)
        pg.wait_for_timeout(500)
        pg.add_style_tag(content="*,*::before,*::after{transition:none!important;animation:none!important}")
        lines = pg.evaluate("() => window.LessonCassette.lines()")
        if not lines:
            result["alert"] = pg.evaluate("() => document.getElementById('alert').innerText")
            browser.close()
            return result, None
        by_scene = {}
        for ln in lines:
            by_scene.setdefault(ln["scene"], []).append(ln)
        for sid, sl in by_scene.items():
            for ln in sl:
                d = ln["end"] - ln["start"]
                t = ln["start"] + max(d / 2, min(0.75, d - 0.02))
                pg.evaluate("(t) => window.LessonCassette.seek(t)", t)
                pg.wait_for_timeout(40)
                res = pg.evaluate(OVERFLOW_JS)
                for r in res[:3]:
                    result["overflow"].append(f"{sid}#{ln['idx']}: {r}")
                for r in pg.evaluate(LOOK_JS):
                    if (sid, r["key"]) not in seen_look:
                        seen_look.add((sid, r["key"]))
                        result["look"].append(f"{sid}#{ln['idx']}: {r['msg']}")
                last = ln is sl[-1]
                if last or sid in frame_tiles:
                    png = pg.locator("#viewport").screenshot()
                    img = Image.open(io.BytesIO(png)).convert("RGB")
                    if last:
                        tiles.append((f"{sid}  ({len(sl)} lines)", img))
                    if sid in frame_tiles:
                        frame_tiles[sid].append((f"{sid}  line {ln['idx']}", img))
        browser.close()
    for i in range(0, len(tiles), SHEET_TILES):
        path = os.path.join(outdir, f"sheet-{i // SHEET_TILES + 1}.png")
        contact_sheet(tiles[i:i + SHEET_TILES], path)
        result["sheets"].append(path)
    for sid, tl in frame_tiles.items():
        if tl:
            path = os.path.join(outdir, f"frames-{sid}.png")
            contact_sheet(tl, path)
            result["frames"].append(path)
        else:
            result["frames"].append(f"（シーン {sid} が見つかりません）")
    return result, None


def contact_sheet(tiles, path, cols=2, tile_w=480):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    scaled = [(lab, im.resize((tile_w, round(im.height * tile_w / im.width)))) for lab, im in tiles]
    th = max(im.height for _, im in scaled) + 24
    rows = math.ceil(len(scaled) / cols)
    sheet = Image.new("RGB", (cols * tile_w + (cols + 1) * 8, rows * th + (rows + 1) * 8), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (lab, im) in enumerate(scaled):
        x, y = 8 + (i % cols) * (tile_w + 8), 8 + (i // cols) * (th + 8)
        dr.text((x, y), lab, fill=(60, 60, 60), font=font)
        sheet.paste(im, (x, y + 22))
        dr.rectangle([x - 1, y + 21, x + tile_w, y + 22 + im.height], outline=(200, 200, 200))
    sheet.save(path)


# ---------------------------------------------------------------- report
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="台本（lessons/*.yaml）か、ビルド済みカセット（dist/*.cassette.json）")
    ap.add_argument("--out", default="qa", help="出力先（既定 qa/、その下に <id>/ を作る）")
    ap.add_argument("--frames", nargs="*", default=[], help="1 行ごとに撮るシーンの id")
    ap.add_argument("--no-screen", action="store_true", help="画面チェックを飛ばす")
    a = ap.parse_args()

    doc = cassette.load(a.source)
    errs, warns = cassette.validate(doc)
    cid = doc.get("id") if isinstance(doc, dict) and isinstance(doc.get("id"), str) else "unknown"
    outdir = os.path.join(a.out, cid)
    os.makedirs(outdir, exist_ok=True)
    for name in os.listdir(outdir):  # 前の回の画像・下書きを消す（どれが最新か紛れないように）
        if re.fullmatch(r"(sheet-\d+|frames-.+)\.png|.+\.draft\.cassette\.json|report\.md", name):
            os.remove(os.path.join(outdir, name))
    must, maybe = [f"形式: {e}" for e in errs], [f"形式: {w}" for w in warns]
    rep = [f"# QA 報告：{doc.get('title', '?')}（{cid}）", "",
           f"- 対象: `{a.source}`", f"- 実行: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    if errs:
        rep += ["", "## 要対応（形式エラーのため、ここで止めました）", ""] + [f"- {m}" for m in must]
        write(outdir, rep)
        print(f"{outdir}/report.md  形式エラー {len(errs)} 件。直してからもう一度実行してください")
        for m in must:
            print("  [要対応]", m)
        sys.exit(1)

    built = "build" in doc
    readings, _ = load_readings()
    scenes = [sc for _, sc in iter_scenes(doc)]
    n_lines = sum(len(sc["lines"]) for sc in scenes)
    n_quiz = sum(sc.get("kind") == "quiz" for sc in scenes)
    secs = doc["duration"] if built and doc.get("duration") else estimate_seconds(doc, readings)
    kind = ("音声入り" if doc.get("audio") else "下書き") if built else "台本"
    if secs > MAX_SECONDS:
        must.append(f"長さ: 約 {secs / 60:.1f} 分。1 本 10 分以内にする（分けるか、削る）")
    elif secs > GOOD_SECONDS:
        maybe.append(f"長さ: 約 {secs / 60:.1f} 分。目安（3〜8 分）を超えています。分けるか削るかを判断し、報告に書く")
    must += check_keys(doc)
    maybe += check_focus(doc)
    no_src = [sc["id"] for sc in scenes if not sc.get("sources") and sc.get("kind") != "quiz"]
    if doc.get("sources") and no_src:
        maybe.append(f"出典: 出典の付いていないシーン {len(no_src)} 個（{'、'.join(no_src)}）。事実を述べるシーンなら付ける")

    # 3. readings
    rows, rmust, rmaybe, flagged = check_readings(doc, readings)
    must += rmust
    maybe += rmaybe
    # 4. graphs
    gmust, gmaybe, facts, lfacts, gcount = check_graphs(doc)
    must += gmust
    maybe += gmaybe
    tmust, tmaybe, tcount = check_tables_more(doc)
    must += tmust
    maybe += tmaybe
    gcount["表と数直線の計算"] = tcount
    cfacts = chart_facts(doc)
    # 5. screen
    screen, skipped = None, None
    if a.no_screen:
        skipped = "--no-screen のため、画面チェックを飛ばしました"
    else:
        target = a.source
        if not built:
            with contextlib.redirect_stdout(io.StringIO()):
                ddoc, _ = build_cassette(a.source, True, "openjtalk", os.path.join(ROOT, "cache"))
            target = os.path.join(outdir, f"{cid}.draft.cassette.json")
            with open(target, "w", encoding="utf-8") as f:
                json.dump(ddoc, f, ensure_ascii=False)
        screen, skipped = check_screen(target, outdir, a.frames)
        if screen:
            if screen["alert"]:
                must.append(f"画面: プレイヤーが読み込めません：{screen['alert']}")
            must += [f"画面: {o}" for o in screen["overflow"]]
            must += [f"画面: スクリプトのエラー {e}" for e in screen["errors"]]
            maybe += [f"見た目: {o}" for o in screen["look"]]

    rep += [f"- 種類: {kind}", f"- 構成: 章 {len(doc['chapters'])}・シーン {len(scenes)}（うち問い {n_quiz}）・台詞 {n_lines} 行",
            f"- 長さ: {'実測' if built and doc.get('duration') else '見積もり 約'} {int(secs // 60)} 分 {int(secs % 60)} 秒",
            f"- 結果: **要対応 {len(must)} 件・要確認 {len(maybe)} 件**・読みの印 {flagged} 行", ""]
    rep += ["## 要対応（直してから先へ進む）", ""] + ([f"- {m}" for m in must] or ["- なし"]) + [""]
    rep += ["## 要確認（意図どおりか確かめる）", ""] + ([f"- {m}" for m in maybe] or ["- なし"]) + [""]
    rep += ["## 読み（Open JTalk のかな読み・読み辞書を当てたあと）", "",
            "全行を目で確かめる。字幕の意味どおりに読めているか、助数詞・数字・英字・同形異音語に特に注意。",
            "直し方：その行だけなら `say`、固有名詞など何度も出る語なら `readings.yaml`。", ""]
    for r in sorted(rows, key=lambda r: not r["marks"]):
        rep.append(f"- **{r['where']}** {r['text']}")
        if r["say"]:
            rep.append(f"  - say: {r['say']}")
        rep.append(f"  - かな: {r['kana']}")
        if r["marks"]:
            rep.append(f"  - 印: {' ／ '.join(r['marks'])}")
    rep += ["", "## グラフと表（台詞・画面の数値と照合する）", "",
            "- 自動で照合した数：" + "・".join(f"{k} {v}" for k, v in gcount.items()) + "（不一致は要対応・要確認に記載）", ""]
    if facts:
        rep += ["### 2 次関数", "", "| 場所 | 行から | 一般形 | 頂点 | 軸 | y 切片 | x 切片 | 向き |", "|---|---|---|---|---|---|---|---|"]
        rep += [f"| {f['where']} | {f['from']} | {f['一般形']} | {f['頂点']} | {f['軸']} | {f['y 切片']} | {f['x 切片']} | {f['向き']} |" for f in facts]
        rep.append("")
    if lfacts:
        rep += ["### 直線", "", "| 場所 | 行から | 式 | 傾き | y 切片 | x 切片 | 向き |", "|---|---|---|---|---|---|---|"]
        rep += [f"| {f['where']} | {f['from']} | {f['式']} | {f['傾き']} | {f['y 切片']} | {f['x 切片']} | {f['向き']} |" for f in lfacts]
        rep.append("")
    if cfacts:
        rep += ["### 棒グラフ・折れ線（台詞の「いちばん多い」などと照合する）", "", "| 場所 | 系列 | 値 | 最大 | 最小 |", "|---|---|---|---|---|"]
        rep += [f"| {f['where']} | {f['name']} | {f['values']} | {f['max']} | {f['min']} |" for f in cfacts]
        rep.append("")
    if not facts and not lfacts and not cfacts:
        rep.append("- 関数のグラフ・データのグラフはありません")
    quizzes = quiz_pairs(doc)
    rep += ["", "## 問い（画面の答えと、答えの台詞が同じ内容か確かめる）", ""]
    rep += [f"- **{q['where']}** 問い：{q['q']}\n  - 画面の答え：{q['a']}\n  - 答えの台詞：{q['line']}" for q in quizzes] or ["- 問いはありません"]
    rep += ["", "## 画面", ""]
    if skipped:
        rep.append(f"- {skipped}")
    elif screen:
        rep.append(f"- はみ出し: {'なし' if not screen['overflow'] else str(len(screen['overflow'])) + ' 件（要対応に記載）'}")
        rep.append(f"- スクリプトのエラー: {'なし' if not screen['errors'] else str(len(screen['errors'])) + ' 件'}")
        rep.append(f"- 見た目の崩れ（ラベルの重なり・式の折り返し・3 文字以下の行）: {'なし' if not screen['look'] else str(len(screen['look'])) + ' 件（要確認に記載）'}")
        rep.append("- 一覧（各シーンの最後の行）: " + "、".join(f"`{os.path.basename(s)}`" for s in screen["sheets"]))
        if screen["frames"]:
            rep.append("- 1 行ごと: " + "、".join(f"`{os.path.basename(s)}`" for s in screen["frames"]))
        rep.append("- 一覧画像は必ず開いて見る：文字の重なり・空きすぎ・強調の付け忘れ・グラフのラベルの位置")
    write(outdir, rep)

    print(f"{outdir}/report.md  [{kind}] 約 {int(secs // 60)} 分 {int(secs % 60)} 秒・台詞 {n_lines} 行")
    print(f"  要対応 {len(must)} 件・要確認 {len(maybe)} 件・読みの印 {flagged} 行")
    for m in must:
        print("  [要対応]", m)
    if skipped:
        print("  [画面]", skipped)
    elif screen:
        print("  [画面] 一覧:", " ".join(screen["sheets"] + [f for f in screen["frames"] if f.endswith(".png")]))
    sys.exit(1 if must else 0)


def write(outdir, rep):
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")


if __name__ == "__main__":
    main()
