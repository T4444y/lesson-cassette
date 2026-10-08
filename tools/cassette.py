"""学習カセット v1 の読み込みと検証（SPEC.md の「検証ルール」をそのままコードにしたもの）。"""
import json
import math
import re

FORMAT, VERSION = "lesson-cassette", 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BLOCK_TYPES = {
    "title": ["text"], "text": ["text"], "bullets": ["items"], "steps": ["items"],
    "compare": ["left", "right"], "formula": ["text"], "code": ["code"],
    "table": ["head", "rows"], "note": ["text"], "quiz": ["question", "answer"], "plot": ["x", "y"],
    "numberline": ["range", "step"], "chart": ["kind", "labels", "series"],
}
CURVE_KINDS = {"quadratic", "line", "vline", "axis", "segment"}
MATH_RE = re.compile(r"[²³√^]")
TIMING_DEFAULTS = {"lead_in": 0.4, "gap": 0.35, "scene_gap": 0.6, "pause_gap": 0.8}
BUILD_ONLY = ("audio", "duration", "build")


def load(path):
    with open(path, encoding="utf-8") as f:
        if path.endswith((".yaml", ".yml")):
            import yaml
            return yaml.safe_load(f)
        return json.load(f)


def validate(doc):
    """(errors, warnings) を返す。どちらも「場所: 内容」の文字列の配列。"""
    E, W = [], []
    if not isinstance(doc, dict):
        return ["全体: JSON のオブジェクトではありません"], []
    if doc.get("format") != FORMAT:
        E.append(f'format: "{FORMAT}" ではありません')
    if doc.get("version") != VERSION:
        E.append(f"version: {VERSION} ではありません（対応していない版です）")
    if not isinstance(doc.get("id"), str) or not ID_RE.match(doc.get("id", "")):
        E.append("id: 英小文字・数字・ハイフンで書いてください")
    if not isinstance(doc.get("title"), str) or not doc.get("title"):
        E.append("title: ありません")
    src_ids = set()
    for i, s in enumerate(doc.get("sources") or []):
        if not isinstance(s, dict) or not s.get("id") or not s.get("label"):
            E.append(f"sources[{i}]: id と label が必要です")
        else:
            src_ids.add(s["id"])
    if not doc.get("sources"):
        W.append("sources: 出典がありません（事実を述べるなら書いてください）")
    chapters = doc.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        E.append("chapters: 1 つ以上必要です")
        return E, W
    seen = set()
    for ci, ch in enumerate(chapters):
        cp = f"chapters[{ci}]"
        if not isinstance(ch, dict):
            E.append(f"{cp}: オブジェクトではありません")
            continue
        _unique(ch.get("id"), cp, seen, E)
        if not ch.get("title"):
            E.append(f"{cp}.title: ありません")
        scenes = ch.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            E.append(f"{cp}.scenes: 1 つ以上必要です")
            continue
        for si, sc in enumerate(scenes):
            _scene(sc, f"{cp}.scenes[{si}]", seen, src_ids, E, W)
    return E, W


def _unique(v, path, seen, E):
    if not isinstance(v, str) or not v:
        E.append(f"{path}.id: ありません")
    elif v in seen:
        E.append(f'{path}.id: "{v}" が重複しています')
    else:
        seen.add(v)


def _scene(sc, sp, seen, src_ids, E, W):
    if not isinstance(sc, dict):
        E.append(f"{sp}: オブジェクトではありません")
        return
    _unique(sc.get("id"), sp, seen, E)
    kind = sc.get("kind", "scene")
    if kind not in ("scene", "quiz"):
        E.append(f'{sp}.kind: "scene" か "quiz" にしてください')
    lines, blocks = sc.get("lines"), sc.get("blocks")
    if not isinstance(lines, list) or not lines:
        E.append(f"{sp}.lines: 1 行以上必要です")
        lines = []
    if not isinstance(blocks, list) or not blocks:
        E.append(f"{sp}.blocks: 1 つ以上必要です")
        blocks = []
    n = len(lines)
    for li, ln in enumerate(lines):
        if not isinstance(ln, dict) or not isinstance(ln.get("text"), str) or not ln.get("text").strip():
            E.append(f"{sp}.lines[{li}].text: ありません")
        else:
            if len(ln["text"]) > 70:
                W.append(f"{sp}.lines[{li}]: 台詞が {len(ln['text'])} 字あります（70 字以内が目安）")
            if MATH_RE.search(ln["text"]) and not ln.get("say"):
                W.append(f"{sp}.lines[{li}]: 数式を含むので say に読みを書いてください")
    if n > 6:
        W.append(f"{sp}.lines: {n} 行あります（6 行以内が目安）")
    if len(blocks) > 4:
        W.append(f"{sp}.blocks: {len(blocks)} 個あります（4 個以内が目安）")
    for s in sc.get("sources") or []:
        if s not in src_ids:
            E.append(f'{sp}.sources: "{s}" は sources にありません')
    quiz_blocks = 0
    for bi, b in enumerate(blocks):
        bp = f"{sp}.blocks[{bi}]"
        if not isinstance(b, dict) or b.get("type") not in BLOCK_TYPES:
            E.append(f'{bp}.type: 未知の部品 "{b.get("type") if isinstance(b, dict) else b}" です')
            continue
        for k in BLOCK_TYPES[b["type"]]:
            if b.get(k) in (None, "", []):
                E.append(f"{bp}.{k}: ありません")
        _timing(b, bp, n, E)
        t = b["type"]
        if t in ("bullets", "steps"):
            items = b.get("items") or []
            if len(items) > 5:
                W.append(f"{bp}.items: {len(items)} 項目あります（5 項目以内が目安）")
            for ii, it in enumerate(items):
                ip = f"{bp}.items[{ii}]"
                if isinstance(it, dict):
                    if t == "steps" and not it.get("title"):
                        E.append(f"{ip}.title: ありません")
                    if t == "bullets" and not it.get("text"):
                        E.append(f"{ip}.text: ありません")
                    _timing(it, ip, n, E)
                elif not (t == "bullets" and isinstance(it, str)):
                    E.append(f"{ip}: 形が違います")
        elif t == "compare":
            if "arrow" in b and not isinstance(b["arrow"], bool):
                E.append(f"{bp}.arrow: true か false にしてください")
            for side in ("left", "right"):
                v = b.get(side)
                if isinstance(v, dict):
                    if not v.get("title"):
                        E.append(f"{bp}.{side}.title: ありません")
                    if v.get("tone", "plain") not in ("plain", "off", "on"):
                        E.append(f'{bp}.{side}.tone: "plain"・"off"・"on" のどれかにしてください')
        elif t == "code" and isinstance(b.get("code"), str) and b["code"].count("\n") >= 10:
            W.append(f"{bp}.code: 10 行を超えています")
        elif t == "table":
            _table(b, bp, n, E, W)
        elif t == "plot":
            _plot(b, bp, n, E)
        elif t == "numberline":
            _numberline(b, bp, n, E)
        elif t == "chart":
            _chart(b, bp, n, E, W)
        elif t == "quiz":
            quiz_blocks += 1
            a = b.get("answer_at", 1)
            if not isinstance(a, int) or not 0 <= a < n:
                E.append(f"{bp}.answer_at: 行の範囲（0〜{n - 1}）の外です")
    if kind == "quiz":
        if quiz_blocks != 1:
            E.append(f"{sp}: quiz シーンには quiz 部品が 1 つ必要です")
        if not any(isinstance(l, dict) and l.get("pause") for l in lines):
            E.append(f"{sp}: quiz シーンには pause: true の行が必要です")


TABLE_WIDTH = 640  # 画面の中身の横幅（表示の単位）
TABLE_STYLES = {"plain": (20, 24), "values": (24, 8), "convert": (26, 8), "matrix": (24, 8)}  # 文字の大きさ, 列の余白


def _cell_units(s):
    """セルの文字幅の見積もり（全角 1・半角 0.6、** と ` は数えない）。"""
    s = str(s).replace("**", "").replace("`", "")
    return sum(6 if ord(ch) < 0x2E80 else 10 for ch in s) / 10  # 整数で数える（JS と同じ値にするため）


def _table(b, bp, n, E, W):
    head, rows = b.get("head") or [], b.get("rows") or []
    if not isinstance(head, list):
        E.append(f"{bp}.head: 配列にしてください")
        return
    style = b.get("style", "plain")
    if style not in TABLE_STYLES:
        E.append(f'{bp}.style: "plain"・"values"・"convert"・"matrix" のどれかにしてください')
        style = "plain"
    cells_by_row = []
    for ri, r in enumerate(rows):
        rp = f"{bp}.rows[{ri}]"
        cells = r.get("cells") if isinstance(r, dict) else r
        if not isinstance(cells, list) or len(cells) != len(head):
            E.append(f"{rp}: 列の数が head と合いません")
            continue
        if any(not isinstance(c, (str, int, float)) or isinstance(c, bool) for c in cells):
            E.append(f"{rp}: セルは文字か数値にしてください")
        if isinstance(r, dict):
            _timing(r, rp, n, E)
        cells_by_row.append(cells)
    cols = b.get("cols")
    if cols is not None:
        if not isinstance(cols, list) or len(cols) != len(head):
            E.append(f"{bp}.cols: head と同じ数の要素（null か {{at, focus}}）にしてください")
        else:
            for ci, c in enumerate(cols):
                if c is None:
                    continue
                if not isinstance(c, dict):
                    E.append(f"{bp}.cols[{ci}]: null か {{at, out, focus}} にしてください")
                else:
                    _timing(c, f"{bp}.cols[{ci}]", n, E)
    align = b.get("align")
    if align is not None and (not isinstance(align, list) or len(align) != len(head)
                              or any(a not in (None, "left", "center", "right") for a in align)):
        E.append(f'{bp}.align: head と同じ数の要素（null・"left"・"center"・"right"）にしてください')
    widths = b.get("widths")
    if widths is not None and (not isinstance(widths, list) or len(widths) != len(head)
                               or any(not _num(w) or w <= 0 for w in widths)):
        E.append(f"{bp}.widths: head と同じ数の正の数（列の幅の比）にしてください")
        widths = None
    if style == "matrix" and len(head) < 2:
        E.append(f"{bp}: matrix の表は 2 列以上にしてください（1 列目が行の見出し）")
    if len(rows) > 5:
        W.append(f"{bp}: 行が {len(rows)} 行あります（5 行以内が目安）")
    font, pad = TABLE_STYLES[style]
    need = [max([_cell_units(h)] + [_cell_units(r[i]) for r in cells_by_row]) * font + pad for i, h in enumerate(head)]
    if style == "plain" and widths is None:
        if sum(need) > TABLE_WIDTH:
            W.append(f"{bp}: 表の横幅が画面に収まらない見込みです（約 {int(sum(need))} / {TABLE_WIDTH}）")
    else:
        ws = widths or [1] * len(head)
        for i, h in enumerate(head):
            avail = TABLE_WIDTH * ws[i] / sum(ws)
            if need[i] > avail:
                W.append(f"{bp}: {i + 1} 列目（{h}）が列の幅に収まらない見込みです（約 {int(need[i])} / {int(avail)}）")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= 1000


def _plot(b, bp, n, E):
    for k in ("x", "y"):
        r = b.get(k)
        if not (isinstance(r, list) and len(r) == 2 and all(_num(v) for v in r) and r[0] < r[1]):
            E.append(f"{bp}.{k}: [最小, 最大] の数値 2 つにしてください")
    h = b.get("height", 230)
    if not (_num(h) and 180 <= h <= 300):
        E.append(f"{bp}.height: 180〜300 にしてください")
    curves, points = b.get("curves") or [], b.get("points") or []
    if not curves and not points:
        E.append(f"{bp}: curves か points のどちらかが必要です")
    quad = set()
    for ci, c in enumerate(curves):
        cp = f"{bp}.curves[{ci}]"
        if not isinstance(c, dict) or c.get("kind") not in CURVE_KINDS:
            E.append(f'{cp}.kind: quadratic・line・vline・axis・segment のどれかにしてください')
            continue
        kind = c["kind"]
        need = {"quadratic": ["a"], "line": ["m", "k"], "vline": ["x"], "axis": [], "segment": []}[kind]
        for k in need:
            if not _num(c.get(k)):
                E.append(f"{cp}.{k}: 数値が必要です")
        if kind == "segment":
            ends = [c.get("from"), c.get("to")]
            if not all(isinstance(e, list) and len(e) == 2 and all(_num(v) for v in e) for e in ends):
                E.append(f"{cp}: from と to に [x, y] を書いてください")
            elif ends[0] == ends[1]:
                E.append(f"{cp}: from と to が同じ点です")
            for k in ("arrow", "dash"):
                if k in c and not isinstance(c[k], bool):
                    E.append(f"{cp}.{k}: true か false にしてください")
            if c.get("keys"):
                E.append(f"{cp}.keys: segment は keys で動かせません")
        if kind == "quadratic":
            vertex_form = all(k in c for k in ("p", "q"))
            general_form = all(k in c for k in ("b", "c"))
            if vertex_form == general_form:
                E.append(f"{cp}: 頂点形（p, q）か一般形（b, c）のどちらか一方で書いてください")
            for k in ("p", "q", "b", "c"):
                if k in c and not _num(c[k]):
                    E.append(f"{cp}.{k}: 数値にしてください")
            if c.get("a") == 0:
                E.append(f"{cp}.a: 0 にはできません")
            quad.add(ci)
        if kind == "axis" and not (isinstance(c.get("of"), int) and c["of"] in quad):
            E.append(f"{cp}.of: それより前にある quadratic の番号にしてください")
        if c.get("color", "accent") not in ("accent", "second", "muted"):
            E.append(f"{cp}.color: accent・second・muted のどれかにしてください")
        for ki, key in enumerate(c.get("keys") or [] if kind != "segment" else []):
            kp = f"{cp}.keys[{ki}]"
            if not isinstance(key, dict) or not (isinstance(key.get("at"), int) and 0 <= key["at"] < n):
                E.append(f"{kp}.at: 行の範囲（0〜{n - 1}）の外です")
                continue
            for k, v in key.items():
                if k == "at":
                    continue
                if k not in ("a", "p", "q", "m", "k", "x") or not _num(v):
                    E.append(f"{kp}.{k}: a・p・q・m・k・x の数値だけが使えます")
                elif k == "a" and v == 0:
                    E.append(f"{kp}.a: 0 にはできません")
            if kind == "quadratic" and "b" in c and any(k in key for k in ("p", "q")):
                E.append(f"{kp}: 一般形（b, c）の曲線は a だけを動かせます")
        _timing(c, cp, n, E)
    for pi, pt in enumerate(points):
        pp = f"{bp}.points[{pi}]"
        if not isinstance(pt, dict):
            E.append(f"{pp}: 形が違います")
            continue
        if "vertex_of" in pt:
            if pt["vertex_of"] not in quad:
                E.append(f"{pp}.vertex_of: quadratic の番号にしてください")
        elif not (_num(pt.get("x")) and _num(pt.get("y"))):
            E.append(f"{pp}: x と y、または vertex_of が必要です")
        _timing(pt, pp, n, E)


def _big(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) <= 1e9


def _numberline(b, bp, n, E):
    r = b.get("range")
    ok = isinstance(r, list) and len(r) == 2 and all(_num(v) for v in r) and r[0] < r[1]
    if not ok:
        E.append(f"{bp}.range: [最小, 最大] の数値 2 つにしてください")
    step = b.get("step")
    if not (_num(step) and step > 0):
        E.append(f"{bp}.step: 正の数にしてください")
    elif ok:
        count = (r[1] - r[0]) / step
        if abs(count - round(count)) > 1e-6:
            E.append(f"{bp}.step: range の幅を割り切れる数にしてください")
        elif round(count) > 40:
            E.append(f"{bp}.step: 目盛りが {round(count)} 個になります（40 個以内）")
    le = b.get("label_every", 1)
    if not (isinstance(le, int) and not isinstance(le, bool) and le >= 1):
        E.append(f"{bp}.label_every: 1 以上の整数にしてください")
    sec = b.get("second")
    if sec is not None and not (isinstance(sec, dict) and _big(sec.get("factor")) and sec.get("factor") != 0):
        E.append(f"{bp}.second: factor（0 以外の数）を持つ {{factor, suffix, name}} にしてください")
    inside = (lambda v: _num(v) and r[0] <= v <= r[1]) if ok else _num
    for i, pt in enumerate(b.get("points") or []):
        pp = f"{bp}.points[{i}]"
        if not isinstance(pt, dict) or not inside(pt.get("value")):
            E.append(f"{pp}.value: range の中の数にしてください")
            continue
        _timing(pt, pp, n, E)
    for i, sp in enumerate(b.get("spans") or []):
        pp = f"{bp}.spans[{i}]"
        if not isinstance(sp, dict) or not (inside(sp.get("from")) and inside(sp.get("to")) and sp["from"] < sp["to"]):
            E.append(f"{pp}: from < to で、range の中の数にしてください")
            continue
        _timing(sp, pp, n, E)
    for i, lb in enumerate(b.get("labels") or []):
        if not isinstance(lb, dict) or not inside(lb.get("value")) or not isinstance(lb.get("text"), (str, int, float)) or isinstance(lb.get("text"), bool):
            E.append(f"{bp}.labels[{i}]: range の中の value と text を書いてください")


def _chart(b, bp, n, E, W):
    if b.get("kind") not in ("bar", "line"):
        E.append(f'{bp}.kind: "bar" か "line" にしてください')
    labels, series = b.get("labels"), b.get("series")
    if not isinstance(labels, list) or not 2 <= len(labels) <= 12 or any(not isinstance(x, (str, int, float)) or isinstance(x, bool) for x in labels):
        E.append(f"{bp}.labels: 2〜12 個の文字か数値にしてください")
        labels = None
    if not isinstance(series, list) or not 1 <= len(series) <= 3:
        E.append(f"{bp}.series: 1〜3 個にしてください")
        return
    vals = []
    for i, se in enumerate(series):
        sp = f"{bp}.series[{i}]"
        if not isinstance(se, dict):
            E.append(f"{sp}: 形が違います")
            continue
        v = se.get("values")
        if not isinstance(v, list) or any(not _big(x) for x in v) or (labels is not None and len(v) != len(labels)):
            E.append(f"{sp}.values: labels と同じ数の数値にしてください")
        else:
            vals += v
        if len(series) > 1 and not (isinstance(se.get("name"), str) and se["name"]):
            E.append(f"{sp}.name: 系列が 2 つ以上なら名前が必要です（凡例に出す）")
        _timing(se, sp, n, E)
    y = b.get("y")
    if y is not None:
        if not (isinstance(y, list) and len(y) == 2 and all(_big(v) for v in y) and y[0] < y[1]):
            E.append(f"{bp}.y: [最小, 最大] の数値 2 つにしてください")
        else:
            if any(v < y[0] or v > y[1] for v in vals):
                E.append(f"{bp}.y: 範囲の外にある値があります")
            if b.get("kind") == "bar" and y[0] > 0:
                W.append(f"{bp}.y: 棒グラフの最小値が 0 ではありません（棒の長さが値に比例しなくなる）")
    h = b.get("height", 230)
    if not (_num(h) and 180 <= h <= 300):
        E.append(f"{bp}.height: 180〜300 にしてください")
    if "values" in b and not isinstance(b["values"], bool):
        E.append(f"{bp}.values: true か false にしてください")


def _timing(o, p, n, E):
    for k in ("at", "out"):
        if k in o and (not isinstance(o[k], int) or not 0 <= o[k] < n):
            E.append(f"{p}.{k}: 行の範囲（0〜{n - 1}）の外です")
    if "focus" in o:
        f = o["focus"]
        if not isinstance(f, list) or any(not isinstance(x, int) or not 0 <= x < n for x in f):
            E.append(f"{p}.focus: 行の範囲（0〜{n - 1}）の番号の配列にしてください")


if __name__ == "__main__":
    import sys
    bad = False
    for path in sys.argv[1:]:
        errs, warns = validate(load(path))
        print(f"{path}: エラー {len(errs)} / 警告 {len(warns)}")
        for e in errs:
            print("  [エラー]", e)
        for w in warns:
            print("  [警告]", w)
        bad |= bool(errs)
    sys.exit(1 if bad else 0)
