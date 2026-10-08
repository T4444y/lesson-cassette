// 学習カセット プレイヤー v1
// カセット（JSON）を読み込み、部品から画面を組み立てて再生する。画面は「時刻 t」だけから描くので、どこに飛んでも同じ絵になる。
// 音声入りカセットは埋め込み音声で、下書きカセットはブラウザの読み上げ（使えなければ無音の時計）で進む。
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const lastAtOrBefore = (arr, x) => { let lo = 0, hi = arr.length - 1, a = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (arr[m].start <= x) { a = m; lo = m + 1; } else hi = m - 1; } return a; };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const store = { get(k) { try { return JSON.parse(localStorage.getItem(`cassette:${k}`)); } catch { return null; } },
                  set(k, v) { try { localStorage.setItem(`cassette:${k}`, JSON.stringify(v)); } catch { /* unavailable */ } } };
  const TIMING = { lead_in: 0.4, gap: 0.35, scene_gap: 0.6, pause_gap: 0.8 };
  const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

  // ================= validation (mirrors tools/cassette.py) =================
  const REQUIRED = { title: ['text'], text: ['text'], bullets: ['items'], steps: ['items'], compare: ['left', 'right'], formula: ['text'],
    code: ['code'], table: ['head', 'rows'], note: ['text'], quiz: ['question', 'answer'], plot: ['x', 'y'],
    numberline: ['range', 'step'], chart: ['kind', 'labels', 'series'] };
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1000;
  const isBig = (v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 1e9;
  const TABLE_STYLES = { plain: [20, 24], values: [24, 8], convert: [26, 8], matrix: [24, 8] };  // font size, column padding
  // width estimate in stage px: full-width chars 1em, half-width 0.6em, at 20px plus 24px padding per column
  const cellUnits = (s) => [...String(s).replace(/\*\*|`/g, '')].reduce((u, ch) => u + (ch.codePointAt(0) < 0x2e80 ? 6 : 10), 0) / 10;  // counted in integers, as in cassette.py
  function validateTable(b, bp, n, E, W, range) {
    const head = b.head;
    if (!Array.isArray(head)) { E.push(`${bp}.head: 配列にしてください`); return; }
    let style = b.style || 'plain';
    if (!(style in TABLE_STYLES)) { E.push(`${bp}.style: "plain"・"values"・"convert"・"matrix" のどれかにしてください`); style = 'plain'; }
    const bodies = [];
    b.rows.forEach((r, ri) => {
      const rp = `${bp}.rows[${ri}]`, cells = r && !Array.isArray(r) && typeof r === 'object' ? r.cells : r;
      if (!Array.isArray(cells) || cells.length !== head.length) { E.push(`${rp}: 列の数が head と合いません`); return; }
      if (cells.some((c) => !(typeof c === 'string' || (typeof c === 'number' && Number.isFinite(c))))) E.push(`${rp}: セルは文字か数値にしてください`);
      if (!Array.isArray(r)) range(r, rp, n);
      bodies.push(cells);
    });
    if (b.cols != null) {
      if (!Array.isArray(b.cols) || b.cols.length !== head.length) E.push(`${bp}.cols: head と同じ数の要素（null か {at, focus}）にしてください`);
      else b.cols.forEach((c, ci) => { if (c == null) return; if (typeof c !== 'object' || Array.isArray(c)) E.push(`${bp}.cols[${ci}]: null か {at, out, focus} にしてください`); else range(c, `${bp}.cols[${ci}]`, n); });
    }
    if (b.align != null && (!Array.isArray(b.align) || b.align.length !== head.length || b.align.some((a) => ![null, 'left', 'center', 'right'].includes(a))))
      E.push(`${bp}.align: head と同じ数の要素（null・"left"・"center"・"right"）にしてください`);
    let widths = b.widths;
    if (widths != null && (!Array.isArray(widths) || widths.length !== head.length || widths.some((w) => !isNum(w) || w <= 0))) {
      E.push(`${bp}.widths: head と同じ数の正の数（列の幅の比）にしてください`); widths = null;
    }
    if (style === 'matrix' && head.length < 2) E.push(`${bp}: matrix の表は 2 列以上にしてください（1 列目が行の見出し）`);
    if (b.rows.length > 5) W.push(`${bp}: 行が ${b.rows.length} 行あります（5 行以内が目安）`);
    const [font, pad] = TABLE_STYLES[style];
    const need = head.map((h, i) => Math.max(cellUnits(h), ...bodies.map((r) => cellUnits(r[i]))) * font + pad);
    if (style === 'plain' && widths == null) {
      const width = need.reduce((x, y) => x + y, 0);
      if (width > 640) W.push(`${bp}: 表の横幅が画面に収まらない見込みです（約 ${Math.floor(width)} / 640）`);
    } else {
      const ws = widths || head.map(() => 1), total = ws.reduce((x, y) => x + y, 0);
      head.forEach((h, i) => { const avail = (640 * ws[i]) / total; if (need[i] > avail) W.push(`${bp}: ${i + 1} 列目（${h}）が列の幅に収まらない見込みです（約 ${Math.floor(need[i])} / ${Math.floor(avail)}）`); });
    }
  }
  function validatePlot(b, bp, n, E, range) {
    for (const k of ['x', 'y']) { const r = b[k]; if (!(Array.isArray(r) && r.length === 2 && r.every(isNum) && r[0] < r[1])) E.push(`${bp}.${k}: [最小, 最大] の数値 2 つにしてください`); }
    const h = b.height ?? 230; if (!(isNum(h) && h >= 180 && h <= 300)) E.push(`${bp}.height: 180〜300 にしてください`);
    const curves = b.curves || [], points = b.points || [], quad = new Set();
    if (!curves.length && !points.length) E.push(`${bp}: curves か points のどちらかが必要です`);
    curves.forEach((c, ci) => {
      const cp = `${bp}.curves[${ci}]`;
      if (!c || !['quadratic', 'line', 'vline', 'axis', 'segment'].includes(c.kind)) { E.push(`${cp}.kind: quadratic・line・vline・axis・segment のどれかにしてください`); return; }
      const need = { quadratic: ['a'], line: ['m', 'k'], vline: ['x'], axis: [], segment: [] }[c.kind];
      for (const k of need) if (!isNum(c[k])) E.push(`${cp}.${k}: 数値が必要です`);
      if (c.kind === 'segment') {
        const ends = [c.from, c.to];
        if (!ends.every((e) => Array.isArray(e) && e.length === 2 && e.every(isNum))) E.push(`${cp}: from と to に [x, y] を書いてください`);
        else if (ends[0][0] === ends[1][0] && ends[0][1] === ends[1][1]) E.push(`${cp}: from と to が同じ点です`);
        for (const k of ['arrow', 'dash']) if (k in c && typeof c[k] !== 'boolean') E.push(`${cp}.${k}: true か false にしてください`);
        if (Array.isArray(c.keys) && c.keys.length) E.push(`${cp}.keys: segment は keys で動かせません`);
      }
      if (c.kind === 'quadratic') {
        const vf = 'p' in c && 'q' in c, gf = 'b' in c && 'c' in c;
        if (vf === gf) E.push(`${cp}: 頂点形（p, q）か一般形（b, c）のどちらか一方で書いてください`);
        for (const k of ['p', 'q', 'b', 'c']) if (k in c && !isNum(c[k])) E.push(`${cp}.${k}: 数値にしてください`);
        if (c.a === 0) E.push(`${cp}.a: 0 にはできません`);
        quad.add(ci);
      }
      if (c.kind === 'axis' && !(Number.isInteger(c.of) && quad.has(c.of))) E.push(`${cp}.of: それより前にある quadratic の番号にしてください`);
      if (!['accent', 'second', 'muted'].includes(c.color || 'accent')) E.push(`${cp}.color: accent・second・muted のどれかにしてください`);
      (c.kind === 'segment' ? [] : c.keys || []).forEach((key, ki) => {
        const kp = `${cp}.keys[${ki}]`;
        if (!key || !(Number.isInteger(key.at) && key.at >= 0 && key.at < n)) { E.push(`${kp}.at: 行の範囲（0〜${n - 1}）の外です`); return; }
        for (const [k, v] of Object.entries(key)) { if (k === 'at') continue; if (!['a', 'p', 'q', 'm', 'k', 'x'].includes(k) || !isNum(v)) E.push(`${kp}.${k}: a・p・q・m・k・x の数値だけが使えます`); else if (k === 'a' && v === 0) E.push(`${kp}.a: 0 にはできません`); }
        if (c.kind === 'quadratic' && 'b' in c && ('p' in key || 'q' in key)) E.push(`${kp}: 一般形（b, c）の曲線は a だけを動かせます`);
      });
      range(c, cp, n);
    });
    points.forEach((pt, pi) => {
      const pp = `${bp}.points[${pi}]`;
      if (!pt || typeof pt !== 'object') { E.push(`${pp}: 形が違います`); return; }
      if ('vertex_of' in pt) { if (!quad.has(pt.vertex_of)) E.push(`${pp}.vertex_of: quadratic の番号にしてください`); }
      else if (!(isNum(pt.x) && isNum(pt.y))) E.push(`${pp}: x と y、または vertex_of が必要です`);
      range(pt, pp, n);
    });
  }
  function validateNumberline(b, bp, n, E, range) {
    const r = b.range, ok = Array.isArray(r) && r.length === 2 && r.every(isNum) && r[0] < r[1];
    if (!ok) E.push(`${bp}.range: [最小, 最大] の数値 2 つにしてください`);
    const step = b.step;
    if (!(isNum(step) && step > 0)) E.push(`${bp}.step: 正の数にしてください`);
    else if (ok) {
      const count = (r[1] - r[0]) / step;
      if (Math.abs(count - Math.round(count)) > 1e-6) E.push(`${bp}.step: range の幅を割り切れる数にしてください`);
      else if (Math.round(count) > 40) E.push(`${bp}.step: 目盛りが ${Math.round(count)} 個になります（40 個以内）`);
    }
    const le = 'label_every' in b ? b.label_every : 1;
    if (!(Number.isInteger(le) && le >= 1)) E.push(`${bp}.label_every: 1 以上の整数にしてください`);
    const sec = b.second;
    if (sec != null && !(typeof sec === 'object' && !Array.isArray(sec) && isBig(sec.factor) && sec.factor !== 0)) E.push(`${bp}.second: factor（0 以外の数）を持つ {factor, suffix, name} にしてください`);
    const inside = (v) => isNum(v) && (!ok || (r[0] <= v && v <= r[1]));
    (b.points || []).forEach((pt, i) => {
      const pp = `${bp}.points[${i}]`;
      if (!pt || typeof pt !== 'object' || !inside(pt.value)) { E.push(`${pp}.value: range の中の数にしてください`); return; }
      range(pt, pp, n);
    });
    (b.spans || []).forEach((sp, i) => {
      const pp = `${bp}.spans[${i}]`;
      if (!sp || typeof sp !== 'object' || !(inside(sp.from) && inside(sp.to) && sp.from < sp.to)) { E.push(`${pp}: from < to で、range の中の数にしてください`); return; }
      range(sp, pp, n);
    });
    (b.labels || []).forEach((lb, i) => {
      if (!lb || typeof lb !== 'object' || !inside(lb.value) || !(typeof lb.text === 'string' || (typeof lb.text === 'number' && Number.isFinite(lb.text)))) E.push(`${bp}.labels[${i}]: range の中の value と text を書いてください`);
    });
  }
  function validateChart(b, bp, n, E, W, range) {
    if (!['bar', 'line'].includes(b.kind)) E.push(`${bp}.kind: "bar" か "line" にしてください`);
    let labels = b.labels; const series = b.series;
    if (!Array.isArray(labels) || labels.length < 2 || labels.length > 12 || labels.some((x) => !(typeof x === 'string' || (typeof x === 'number' && Number.isFinite(x))))) { E.push(`${bp}.labels: 2〜12 個の文字か数値にしてください`); labels = null; }
    if (!Array.isArray(series) || series.length < 1 || series.length > 3) { E.push(`${bp}.series: 1〜3 個にしてください`); return; }
    const vals = [];
    series.forEach((se, i) => {
      const sp = `${bp}.series[${i}]`;
      if (!se || typeof se !== 'object' || Array.isArray(se)) { E.push(`${sp}: 形が違います`); return; }
      const v = se.values;
      if (!Array.isArray(v) || v.some((x) => !isBig(x)) || (labels && v.length !== labels.length)) E.push(`${sp}.values: labels と同じ数の数値にしてください`);
      else vals.push(...v);
      if (series.length > 1 && !(typeof se.name === 'string' && se.name)) E.push(`${sp}.name: 系列が 2 つ以上なら名前が必要です（凡例に出す）`);
      range(se, sp, n);
    });
    const y = b.y;
    if (y != null) {
      if (!(Array.isArray(y) && y.length === 2 && y.every(isBig) && y[0] < y[1])) E.push(`${bp}.y: [最小, 最大] の数値 2 つにしてください`);
      else {
        if (vals.some((v) => v < y[0] || v > y[1])) E.push(`${bp}.y: 範囲の外にある値があります`);
        if (b.kind === 'bar' && y[0] > 0) W.push(`${bp}.y: 棒グラフの最小値が 0 ではありません（棒の長さが値に比例しなくなる）`);
      }
    }
    const h = b.height ?? 230; if (!(isNum(h) && h >= 180 && h <= 300)) E.push(`${bp}.height: 180〜300 にしてください`);
    if ('values' in b && typeof b.values !== 'boolean') E.push(`${bp}.values: true か false にしてください`);
  }
  function validate(doc) {
    const E = [], W = [];
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return { errors: ['全体: JSON のオブジェクトではありません'], warnings: [] };
    if (doc.format !== 'lesson-cassette') E.push('format: "lesson-cassette" ではありません');
    if (doc.version !== 1) E.push('version: 1 ではありません（このプレイヤーが対応していない版です）');
    if (typeof doc.id !== 'string' || !/^[a-z0-9][a-z0-9-]*$/.test(doc.id)) E.push('id: 英小文字・数字・ハイフンで書いてください');
    if (typeof doc.title !== 'string' || !doc.title) E.push('title: ありません');
    const srcIds = new Set();
    (Array.isArray(doc.sources) ? doc.sources : []).forEach((s, i) => { if (!s || !s.id || !s.label) E.push(`sources[${i}]: id と label が必要です`); else srcIds.add(s.id); });
    if (!Array.isArray(doc.sources) || !doc.sources.length) W.push('sources: 出典がありません');
    if (!Array.isArray(doc.chapters) || !doc.chapters.length) { E.push('chapters: 1 つ以上必要です'); return { errors: E, warnings: W }; }
    const seen = new Set();
    const uniq = (v, p) => { if (typeof v !== 'string' || !v) E.push(`${p}.id: ありません`); else if (seen.has(v)) E.push(`${p}.id: "${v}" が重複しています`); else seen.add(v); };
    const range = (o, p, n) => {
      for (const k of ['at', 'out']) if (k in o && !(Number.isInteger(o[k]) && o[k] >= 0 && o[k] < n)) E.push(`${p}.${k}: 行の範囲（0〜${n - 1}）の外です`);
      if ('focus' in o && !(Array.isArray(o.focus) && o.focus.every((x) => Number.isInteger(x) && x >= 0 && x < n))) E.push(`${p}.focus: 行の範囲（0〜${n - 1}）の番号の配列にしてください`);
    };
    doc.chapters.forEach((ch, ci) => {
      const cp = `chapters[${ci}]`;
      if (!ch || typeof ch !== 'object') { E.push(`${cp}: オブジェクトではありません`); return; }
      uniq(ch.id, cp); if (!ch.title) E.push(`${cp}.title: ありません`);
      if (!Array.isArray(ch.scenes) || !ch.scenes.length) { E.push(`${cp}.scenes: 1 つ以上必要です`); return; }
      ch.scenes.forEach((sc, si) => {
        const sp = `${cp}.scenes[${si}]`;
        if (!sc || typeof sc !== 'object') { E.push(`${sp}: オブジェクトではありません`); return; }
        uniq(sc.id, sp);
        const kind = sc.kind || 'scene'; if (kind !== 'scene' && kind !== 'quiz') E.push(`${sp}.kind: "scene" か "quiz" にしてください`);
        const lines = Array.isArray(sc.lines) ? sc.lines : [], blocks = Array.isArray(sc.blocks) ? sc.blocks : [], n = lines.length;
        if (!n) E.push(`${sp}.lines: 1 行以上必要です`);
        if (!blocks.length) E.push(`${sp}.blocks: 1 つ以上必要です`);
        lines.forEach((ln, li) => {
          if (!ln || typeof ln.text !== 'string' || !ln.text.trim()) { E.push(`${sp}.lines[${li}].text: ありません`); return; }
          if (ln.text.length > 70) W.push(`${sp}.lines[${li}]: 台詞が ${ln.text.length} 字あります`);
          if (/[²³√^]/.test(ln.text) && !ln.say) W.push(`${sp}.lines[${li}]: 数式を含むので say に読みを書いてください`);
        });
        if (n > 6) W.push(`${sp}.lines: ${n} 行あります（6 行以内が目安）`);
        if (blocks.length > 4) W.push(`${sp}.blocks: ${blocks.length} 個あります（4 個以内が目安）`);
        for (const s of sc.sources || []) if (!srcIds.has(s)) E.push(`${sp}.sources: "${s}" は sources にありません`);
        let quizzes = 0;
        blocks.forEach((b, bi) => {
          const bp = `${sp}.blocks[${bi}]`;
          if (!b || !REQUIRED[b.type]) { E.push(`${bp}.type: 未知の部品 "${b && b.type}" です`); return; }
          for (const k of REQUIRED[b.type]) if (b[k] == null || b[k] === '' || (Array.isArray(b[k]) && !b[k].length)) E.push(`${bp}.${k}: ありません`);
          range(b, bp, n);
          if ((b.type === 'bullets' || b.type === 'steps') && Array.isArray(b.items)) {
            if (b.items.length > 5) W.push(`${bp}.items: ${b.items.length} 項目あります`);
            b.items.forEach((it, ii) => {
              const ip = `${bp}.items[${ii}]`;
              if (it && typeof it === 'object') { if (b.type === 'steps' && !it.title) E.push(`${ip}.title: ありません`); if (b.type === 'bullets' && !it.text) E.push(`${ip}.text: ありません`); range(it, ip, n); }
              else if (!(b.type === 'bullets' && typeof it === 'string')) E.push(`${ip}: 形が違います`);
            });
          }
          if (b.type === 'compare' && 'arrow' in b && typeof b.arrow !== 'boolean') E.push(`${bp}.arrow: true か false にしてください`);
          if (b.type === 'compare') for (const side of ['left', 'right']) { const v = b[side]; if (v && typeof v === 'object') { if (!v.title) E.push(`${bp}.${side}.title: ありません`); if (!['plain', 'off', 'on'].includes(v.tone || 'plain')) E.push(`${bp}.${side}.tone: 値が違います`); } }
          if (b.type === 'table' && Array.isArray(b.rows)) validateTable(b, bp, n, E, W, range);
          if (b.type === 'plot') validatePlot(b, bp, n, E, range);
          if (b.type === 'numberline') validateNumberline(b, bp, n, E, range);
          if (b.type === 'chart') validateChart(b, bp, n, E, W, range);
          if (b.type === 'quiz') { quizzes++; const a = b.answer_at ?? 1; if (!(Number.isInteger(a) && a >= 0 && a < n)) E.push(`${bp}.answer_at: 行の範囲の外です`); }
        });
        if (kind === 'quiz') { if (quizzes !== 1) E.push(`${sp}: quiz シーンには quiz 部品が 1 つ必要です`); if (!lines.some((l) => l && l.pause)) E.push(`${sp}: quiz シーンには pause: true の行が必要です`); }
      });
    });
    return { errors: E, warnings: W };
  }

  // ================= timeline =================
  // 音声入りはビルドが書いた start/end を使う。下書きは文字数から長さを見積もる（ビルドと同じ無音の入れ方）。
  function flatten(doc) {
    const tm = { ...TIMING, ...(doc.timing || {}) }, timed = !!doc.audio;
    const lines = [], scenes = [], chapters = [];
    let t = tm.lead_in, prev = null;
    for (const ch of doc.chapters) {
      const chStart = lines.length ? lines[lines.length - 1].end : 0;
      for (const sc of ch.scenes) {
        const scStart = lines.length ? lines[lines.length - 1].end : 0;
        sc.lines.forEach((ln, idx) => {
          let start, end;
          if (timed) { start = ln.start; end = ln.end; }
          else {
            if (prev) t += Math.max(tm.gap, idx === 0 ? tm.scene_gap : 0, prev.pause ? tm.pause_gap : 0);
            const say = ln.say || ln.text;
            start = t; end = t + Math.max(1.2, [...say].length * 0.15); t = end;
          }
          const L = { scene: sc.id, chapter: ch.id, idx, text: ln.text, say: ln.say || ln.text, chunks: ln.chunks, pause: !!ln.pause, start, end };
          lines.push(L); prev = L;
        });
        scenes.push({ id: sc.id, chapter: ch.id, kind: sc.kind || 'scene', sources: sc.sources || [], start: scStart });
      }
      chapters.push({ id: ch.id, title: ch.title, start: chStart });
    }
    const duration = timed && doc.duration ? doc.duration : lines[lines.length - 1].end + 0.8;
    for (const arr of [scenes, chapters]) arr.forEach((it, i) => { it.end = i + 1 < arr.length ? arr[i + 1].start : duration; });
    return { lines, scenes, chapters, duration, timed };
  }

  // ================= components =================
  // Japanese has no spaces, so a browser may break a line in the middle of a word. Mark rough phrase boundaries
  // with <wbr>: after punctuation, before an opening bracket, and where a run of hiragana gives way to kanji,
  // katakana, Latin letters or digits ("時速30kmの|バスは|時速何km"). The CSS (word-break: keep-all) keeps
  // block text from breaking anywhere else; a phrase too long for the line still breaks (overflow-wrap).
  const HIRA = /[\u3041-\u309f]/, WORDY = /[\u3005\u4e00-\u9fff\u30a1-\u30fa\u30fcA-Za-z0-9\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]/;
  const OPEN_B = /[（「『【〈《]/, AFTER_B = /[、。，！？・]/, CLOSE_B = /[）」』】〉》]/, PARTICLE = /[はがにとへも]/;
  function phrased(target, s) {
    s = s.replace(/(\d) ([-−–×÷=＝+]) (?=\d)/g, '$1\u00a0$2\u00a0');  // keep "6 - 5" and "2 × 3" on one line
    let cur = '', prev = '', prev2 = '';
    for (const ch of s) {
      const brk = (HIRA.test(prev) && WORDY.test(ch)) || OPEN_B.test(ch) || AFTER_B.test(prev) || (CLOSE_B.test(prev) && !HIRA.test(ch))
        // a particle right after a word: 単位を|そろえて, バスは|どちら
        || (HIRA.test(ch) && (prev === 'を' || (PARTICLE.test(prev) && WORDY.test(prev2))));
      if (cur && brk) { target.append(document.createTextNode(cur), el('wbr')); cur = ''; }
      cur += ch; prev2 = prev; prev = ch;
    }
    if (cur) target.append(document.createTextNode(cur));
    return target;
  }
  function rich(target, s) {
    // only **strong** and `code`; everything else is plain text
    for (const part of String(s).split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
      if (!part) continue;
      if (part.startsWith('**') && part.endsWith('**')) target.append(phrased(el('strong'), part.slice(2, -2)));
      else if (part.startsWith('`') && part.endsWith('`')) target.append(el('code', null, part.slice(1, -1)));
      else phrased(target, part);
    }
    return target;
  }
  const timing = (e, o) => {
    if (o && o.at != null) e.dataset.at = String(o.at);
    if (o && o.out != null) e.dataset.out = String(o.out);
    if (o && Array.isArray(o.focus)) e.dataset.focus = o.focus.join(',');
    return e;
  };
  const card = (c) => {
    const d = el('div', `card ${c.tone || 'plain'}`);
    if (c.label) d.append(el('span', 'lab', c.label));
    d.append(rich(el('b', 'mk'), c.title)); if (c.note) d.append(rich(el('small'), c.note)); return d;
  };
  const BLOCKS = {
    title: (b) => { const d = el('div', 'b-title'); if (b.kicker) d.append(el('p', 'sc-kicker', b.kicker)); d.append(rich(el('h2', 'sc-title'), b.text)); return d; },
    text: (b) => rich(el('p', 'sc-text mk'), b.text),
    bullets: (b) => { const u = el('ul', 'sum'); for (const it of b.items) { const o = typeof it === 'string' ? { text: it } : it; u.append(timing(rich(el('li', 'mk'), o.text), o)); } return u; },
    steps: (b) => { const o = el('ol', 'steps'); b.items.forEach((it, i) => { const li = el('li'); li.append(el('span', 'num', String(i + 1)), rich(el('b', 'mk'), it.title)); if (it.note) li.append(rich(el('small'), it.note)); o.append(timing(li, it)); }); return o; },
    compare: (b) => { const r = el('div', 'sc-row'); r.append(card(b.left)); if (b.arrow !== false) r.append(el('div', 'arrow', '→')); r.append(card(b.right)); return r; },
    formula: (b) => el('p', 'formula', b.text),
    code: (b) => { const p = el('pre', 'sc-code'); p.append(el('code', null, b.code)); return p; },
    table: (b) => {
      // rows: [cells] or {cells, at, out, focus}; cols[i]: {at, out, focus} — a column's at/out apply to its body cells
      // (the header stays as the guide), its focus highlights the whole column
      const t = el('table', `sc-table${b.style && b.style !== 'plain' ? ` ${b.style}` : ''}`), cols = b.cols || [];
      if (Array.isArray(b.widths)) {
        const total = b.widths.reduce((x, y) => x + y, 0), cg = el('colgroup');
        for (const w of b.widths) { const c = el('col'); c.style.width = `${((100 * w) / total).toFixed(2)}%`; cg.append(c); }
        t.append(cg); t.style.tableLayout = 'fixed';
      }
      const colTiming = (cell, ci, header) => {
        const c = cols[ci]; if (!c) return cell;
        if (!header && c.at != null) cell.dataset.at = String(c.at);
        if (!header && c.out != null) cell.dataset.out = String(c.out);
        if (Array.isArray(c.focus)) cell.dataset.focus = c.focus.join(',');
        return cell;
      };
      const hr = el('tr'); b.head.forEach((h, ci) => hr.append(colTiming(rich(el('th'), h), ci, true)));
      const tb = el('tbody');
      for (const row of b.rows) {
        const o = Array.isArray(row) ? { cells: row } : row, tr = timing(el('tr'), o);
        o.cells.forEach((c, ci) => tr.append(colTiming(rich(el('td'), c), ci, false)));
        tb.append(tr);
      }
      const th = el('thead'); th.append(hr); t.append(th, tb);
      // a one-letter row label (x, y) is a variable: set it in italics; words and numbers stay upright
      for (const r of t.rows) { const c = r.cells[0]; if (c && /^[A-Za-z]$/.test(c.textContent.trim())) c.classList.add('var'); }
      if (Array.isArray(b.align)) for (const r of t.rows) [...r.cells].forEach((c, ci) => { if (b.align[ci]) c.style.textAlign = b.align[ci]; });
      return t;
    },
    note: (b) => { const d = el('div', 'sc-note'); d.append(el('span', 'tag', b.label || '補足'), rich(el('p'), b.text)); return d; },
    quiz: (b) => {
      const d = el('div', 'quiz'); d.append(el('p', 'quiz-tag', '止めて考える'), rich(el('p', 'quiz-q'), b.question));
      const a = rich(el('p', 'quiz-a'), b.answer); a.dataset.at = String(b.answer_at ?? 1); d.append(a); return d;
    },
  };
  // ================= plot (function graphs) =================
  // The block stores only numbers; the curve shape at time t is computed here, so a seek draws the same frame as playback.
  const SVGNS = 'http://www.w3.org/2000/svg', PLOT_W = 640, MORPH = 0.7, PARAMS = ['a', 'p', 'q', 'm', 'k', 'x'];
  const sv = (tag, attrs = {}) => { const e = document.createElementNS(SVGNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  const fmtNum = (v) => { let r = Math.round(v * 10) / 10; if (Object.is(r, -0)) r = 0; return String(r).replace('-', '−'); };
  const ease = (u) => u * u * (3 - 2 * u);
  const baseParams = (c) => {
    if (c.kind === 'quadratic') return 'b' in c ? { a: c.a, b: c.b, c: c.c, general: true, p: -c.b / (2 * c.a), q: c.c - (c.b * c.b) / (4 * c.a) } : { a: c.a, p: c.p, q: c.q };
    if (c.kind === 'line') return { m: c.m, k: c.k };
    if (c.kind === 'vline') return { x: c.x };
    return {};
  };
  const withKey = (cur, key) => {
    const n = { ...cur }; for (const k of PARAMS) if (k in key) n[k] = key[k];
    if (n.general && 'a' in key) { n.p = -n.b / (2 * n.a); n.q = n.c - (n.b * n.b) / (4 * n.a); }
    return n;
  };
  function paramsAt(c, idx, t, lineStart) {
    let cur = baseParams(c), prev = cur, lastAt = -1;
    for (const key of [...(c.keys || [])].sort((x, y) => x.at - y.at)) { if (key.at > idx) break; prev = cur; cur = withKey(cur, key); lastAt = key.at; }
    if (lastAt < 0) return cur;
    const u = ease(clamp01((t - lineStart(lastAt)) / MORPH));
    if (u >= 1) return cur;
    const out = { ...cur }; for (const k of PARAMS) if (k in cur && k in prev) out[k] = prev[k] + (cur[k] - prev[k]) * u;
    return out;
  }
  const fillTemplate = (s, prm) => String(s).replace(/\{([apqmkx])\}/g, (m, k) => (k in prm ? fmtNum(prm[k]) : m));

  function plotBlock(b) {
    const H = b.height || 230, P = { l: 30, r: 16, t: 12, b: 28 };
    const [x0, x1] = b.x, [y0, y1] = b.y, iw = PLOT_W - P.l - P.r, ih = H - P.t - P.b;
    const sx = (x) => P.l + ((x - x0) / (x1 - x0)) * iw, sy = (y) => P.t + ((y1 - y) / (y1 - y0)) * ih;
    const svg = sv('svg', { viewBox: `0 0 ${PLOT_W} ${H}`, width: PLOT_W, height: H, class: 'b-plot', role: 'img', 'aria-label': 'グラフ' });
    const clipId = `pc${Math.random().toString(36).slice(2, 9)}`;
    const defs = sv('defs'), clip = sv('clipPath', { id: clipId });
    clip.append(sv('rect', { x: P.l, y: P.t, width: iw, height: ih })); defs.append(clip); svg.append(defs);
    // grid, axes and tick labels
    // tick every 1, or every 2 when units would sit closer than ~26 stage px
    const stepX = x1 - x0 > 12 || iw / (x1 - x0) < 26 ? 2 : 1, stepY = y1 - y0 > 12 || ih / (y1 - y0) < 26 ? 2 : 1;
    for (let v = Math.ceil(x0 / stepX) * stepX; v <= x1 + 1e-9; v += stepX) {
      svg.append(sv('line', { x1: sx(v), x2: sx(v), y1: P.t, y2: P.t + ih, class: v === 0 ? 'pl-axis' : 'pl-grid' }));
      // the label at the left end starts at the edge, clear of the y labels in the corner
      if (v !== 0) { const tx = sv('text', { x: sx(v), y: H - 8, class: 'pl-tick', 'text-anchor': Math.abs(v - x0) < 1e-9 ? 'start' : 'middle' }); tx.textContent = fmtNum(v); svg.append(tx); }
    }
    for (let v = Math.ceil(y0 / stepY) * stepY; v <= y1 + 1e-9; v += stepY) {
      svg.append(sv('line', { x1: P.l, x2: P.l + iw, y1: sy(v), y2: sy(v), class: v === 0 ? 'pl-axis' : 'pl-grid' }));
      if (v !== 0) { const ty = sv('text', { x: P.l - 6, y: sy(v) + 5, class: 'pl-tick', 'text-anchor': 'end' }); ty.textContent = fmtNum(v); svg.append(ty); }
    }
    let originEl = null;
    if (x0 <= 0 && 0 <= x1 && y0 <= 0 && 0 <= y1) { const o = sv('text', { x: sx(0) - 6, y: sy(0) + 18, class: 'pl-origin', 'text-anchor': 'end' }); o.textContent = 'O'; svg.append(o); originEl = o; }
    const curves = (b.curves || []).map((c) => {
      const dashed = c.kind === 'axis' || c.kind === 'vline' || (c.kind === 'segment' && c.dash);
      const g = timing(sv('g', { class: `pl-curve pl-${c.color || 'accent'}${dashed ? ' pl-dash' : ''}` }), c);
      const path = sv('path', { 'clip-path': `url(#${clipId})` }); g.append(path);
      const head = c.kind === 'segment' && c.arrow ? sv('path', { class: 'pl-head' }) : null; if (head) g.append(head);
      const lab = c.label ? sv('text', { class: 'pl-label' }) : null; if (lab) g.append(lab);
      svg.append(g); return { c, g, path, head, lab, prev: -1 };
    });
    const points = (b.points || []).map((pt) => {
      const g = timing(sv('g', { class: 'pl-pt' }), pt), dot = sv('circle', { r: 6 }), lab = pt.label ? sv('text', {}) : null;
      g.append(dot); if (lab) g.append(lab); svg.append(g); return { pt, g, dot, lab, prev: -1 };
    });
    const shown = (g) => !((g.dataset.at != null && !g.classList.contains('on')) || g.classList.contains('gone'));
    const inPlot = (r) => r.x >= P.l + 2 && r.y >= P.t + 2 && r.x + r.w <= P.l + iw - 2 && r.y + r.h <= P.t + ih - 2;
    const overlap = (a, r, m = 2) => a.x < r.x + r.w + m && a.x + a.w + m > r.x && a.y < r.y + r.h + m && a.y + a.h + m > r.y;
    // does the segment p-q cross the rectangle r? (Liang-Barsky clip)
    const segHits = (p, q, r) => {
      let t0 = 0, t1 = 1; const dx = q[0] - p[0], dy = q[1] - p[1];
      for (const [pp, qq] of [[-dx, p[0] - r.x], [dx, r.x + r.w - p[0]], [-dy, p[1] - r.y], [dy, r.y + r.h - p[1]]]) {
        if (pp === 0) { if (qq < 0) return false; continue; }
        const t = qq / pp; if (pp < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
      }
      return true;
    };
    const lineHits = (pts, r) => { for (let i = 1; i < pts.length; i++) if (segHits(pts[i - 1], pts[i], r)) return true; return false; };
    const axes = [];
    if (y0 <= 0 && 0 <= y1) axes.push([[P.l, sy(0)], [P.l + iw, sy(0)]]);
    if (x0 <= 0 && 0 <= x1) axes.push([[sx(0), P.t], [sx(0), P.t + ih]]);
    svg.__update = (idx, t, lineStart) => {
      const prm = curves.map(({ c }) => paramsAt(c, idx, t, lineStart));
      const lo = y0 - (y1 - y0) * 2, hi = y1 + (y1 - y0) * 2, clampY = (y) => Math.max(lo, Math.min(hi, y));
      const inY = (y) => y >= y0 + (y1 - y0) * 0.08 && y <= y1 - (y1 - y0) * 0.08;
      const lines = [], jobs = [];
      curves.forEach((o, i) => {
        const { c, path, head, lab } = o, p = c.kind === 'axis' ? { x: prm[c.of].p } : prm[i];
        let d = '', pts = [], cand = [];
        const around = (ax, ay) => [[ax + 10, ay - 10, 'start'], [ax - 10, ay - 10, 'end'], [ax + 10, ay + 26, 'start'], [ax - 10, ay + 26, 'end']];
        if (c.kind === 'quadratic') {
          const N = 160, f = (x) => p.a * (x - p.p) ** 2 + p.q;
          for (let s = 0; s <= N; s++) { const x = x0 + ((x1 - x0) * s) / N; pts.push([sx(x), sy(clampY(f(x)))]); }
          // anchors: the right-most visible point first (the old default), then points spread over the visible part
          const vis = []; for (let s = 0; s <= N; s++) { const x = x0 + ((x1 - x0) * s) / N; if (inY(f(x))) vis.push([sx(x), sy(f(x))]); }
          if (!vis.length) vis.push([sx(p.p), sy(Math.max(y0, Math.min(y1, p.q)))]);
          const order = [1, 0.85, 0.7, 0.5, 0.3, 0.15, 0].map((u) => vis[Math.round(u * (vis.length - 1))]);
          for (const [ax, ay] of order) cand.push(...around(ax, ay));
        } else if (c.kind === 'line') {
          pts = [[sx(x0), sy(clampY(p.m * x0 + p.k))], [sx(x1), sy(clampY(p.m * x1 + p.k))]];
          for (const u of [0.88, 0.7, 0.5, 0.3, 0.12]) { const x = x0 + (x1 - x0) * u, y = p.m * x + p.k; if (inY(y)) cand.push(...around(sx(x), sy(y))); }
          if (!cand.length) cand.push(...around(sx(x1 - (x1 - x0) * 0.12), sy(Math.max(y0, Math.min(y1, p.m * (x1 - (x1 - x0) * 0.12) + p.k)))));
        } else if (c.kind === 'segment') {
          const A = [sx(c.from[0]), sy(c.from[1])], B = [sx(c.to[0]), sy(c.to[1])], len = Math.hypot(B[0] - A[0], B[1] - A[1]) || 1;
          const ux = (B[0] - A[0]) / len, uy = (B[1] - A[1]) / len, back = head ? 10 : 0, E2 = [B[0] - ux * back, B[1] - uy * back];
          pts = [A, B];
          d = `M${A[0].toFixed(1)} ${A[1].toFixed(1)}L${E2[0].toFixed(1)} ${E2[1].toFixed(1)}`;
          if (head) head.setAttribute('d', `M${B[0].toFixed(1)} ${B[1].toFixed(1)}L${(B[0] - ux * 14 - uy * 7).toFixed(1)} ${(B[1] - uy * 14 + ux * 7).toFixed(1)}L${(B[0] - ux * 14 + uy * 7).toFixed(1)} ${(B[1] - uy * 14 - ux * 7).toFixed(1)}Z`);
          const M = [(A[0] + B[0]) / 2, (A[1] + B[1]) / 2];
          for (const sgn of [1, -1]) { const nx = -uy * sgn, ny = ux * sgn; cand.push([M[0] + nx * 12, M[1] + ny * 12 + 7, nx > 0.3 ? 'start' : nx < -0.3 ? 'end' : 'middle']); }
        } else {
          pts = [[sx(p.x), P.t], [sx(p.x), P.t + ih]];
          cand = [[sx(p.x) + 8, P.t + 22, 'start'], [sx(p.x) - 8, P.t + 22, 'end'], [sx(p.x) + 8, P.t + ih - 10, 'start'], [sx(p.x) - 8, P.t + ih - 10, 'end']];
        }
        if (c.kind !== 'segment') d = pts.map(([x, y], s) => `${s ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join('');
        path.setAttribute('d', d);
        if (shown(o.g)) lines.push(pts);
        if (lab) { lab.textContent = fillTemplate(c.label, p); jobs.push({ o, lab, cand }); }
      });
      const dots = [];
      points.forEach((o) => {
        const { pt, dot, lab } = o, v = 'vertex_of' in pt ? prm[pt.vertex_of] : { x: pt.x, y: pt.y };
        const x = 'vertex_of' in pt ? v.p : v.x, y = 'vertex_of' in pt ? v.q : v.y, cx = sx(x), cy = sy(y);
        dot.setAttribute('cx', cx); dot.setAttribute('cy', cy);
        if (shown(o.g)) dots.push({ cx, cy, g: o.g });
        if (lab) {
          lab.textContent = fillTemplate(pt.label, { ...v, x, y });
          // the ring next to the dot first, then a wider ring (still read as the dot's label)
          jobs.push({ o, lab, cand: [[cx + 10, cy - 10, 'start'], [cx - 10, cy - 10, 'end'], [cx + 10, cy + 26, 'start'], [cx - 10, cy + 26, 'end'], [cx, cy - 14, 'middle'], [cx, cy + 30, 'middle'],
            [cx + 14, cy + 7, 'start'], [cx - 14, cy + 7, 'end'], [cx + 18, cy - 30, 'start'], [cx - 18, cy - 30, 'end'], [cx + 18, cy + 46, 'start'], [cx - 18, cy + 46, 'end']] });
        }
      });
      // place each visible label at the first candidate clear of every line, dot and earlier label (keep last frame's choice while it stays clear)
      const placed = [];
      if (originEl) { const bb = originEl.getBBox(); placed.push({ x: bb.x, y: bb.y, w: bb.width, h: bb.height }); }  // keep labels off the origin mark
      for (const { o, lab, cand } of jobs) {
        if (!shown(o.g)) continue;
        lab.setAttribute('x', 0); lab.setAttribute('y', 0); lab.setAttribute('text-anchor', 'start');
        const bb = lab.getBBox();
        const rectOf = ([x, y, anchor]) => ({ x: anchor === 'start' ? x : anchor === 'end' ? x - bb.width : x - bb.width / 2, y: y + bb.y, w: bb.width, h: bb.height });
        const cost = (k, strict) => {
          const r = rectOf(cand[k]); if (!inPlot(r)) return Infinity;
          let n = 0;
          for (const pts of lines) if (lineHits(pts, r)) n += 10;
          for (const dd of dots) if (dd.g !== o.g && dd.cx > r.x - 8 && dd.cx < r.x + r.w + 8 && dd.cy > r.y - 8 && dd.cy < r.y + r.h + 8) n += 5;
          for (const q of placed) if (overlap(q, r)) n += 20;
          if (strict) for (const ax of axes) if (lineHits(ax, r)) n += 1;
          return n;
        };
        let pick = -1;
        if (o.prev >= 0 && o.prev < cand.length && cost(o.prev, false) === 0) pick = o.prev;
        for (const strict of [true, false]) { if (pick >= 0) break; for (let k = 0; k < cand.length; k++) if (cost(k, strict) === 0) { pick = k; break; } }
        if (pick < 0) { let best = Infinity; cand.forEach((_, k) => { const v = cost(k, false); if (v < best) { best = v; pick = k; } }); if (pick < 0) pick = 0; }
        o.prev = pick;
        const [x, y, anchor] = cand[pick];
        lab.setAttribute('x', x.toFixed(1)); lab.setAttribute('y', y.toFixed(1)); lab.setAttribute('text-anchor', anchor);
        placed.push(rectOf(cand[pick]));
      }
    };
    return svg;
  }
  BLOCKS.plot = plotBlock;

  // ================= number line =================
  // A line with ticks; an optional second scale under it (double number line: 0.35 above, 35% below), points and spans on it.
  const fmtTick = (v) => String(Number(v.toFixed(10))).replace('-', '−');
  function numberlineBlock(b) {
    const [lo, hi] = b.range, step = b.step, sec = b.second;
    // tick labels (estimated widths), then margins: room for the names on the left and for half of the first and last
    // tick labels, so that nothing runs off the drawing
    const labelW = (str) => [...str].reduce((u, ch) => u + (ch.codePointAt(0) < 0x2e80 ? 11 : 19), 0) + 10;
    const custom = new Map((b.labels || []).map((l) => [Number(l.value.toFixed(10)), String(l.text)]));
    const tickText = (v) => { const k = Number(v.toFixed(10)); return custom.has(k) ? custom.get(k) : `${fmtTick(v)}${b.suffix || ''}`; };
    const secText = (v) => `${sec.prefix || ''}${fmtTick(v * sec.factor)}${sec.suffix || ''}`;
    const edgeHalf = (v) => Math.max(labelW(tickText(v)), sec ? labelW(secText(v)) : 0) / 2;
    const nameW = Math.max(0, ...[b.name, sec && sec.name].filter(Boolean).map((t) => [...String(t)].reduce((u, ch) => u + (ch.codePointAt(0) < 0x2e80 ? 9 : 16), 0)));
    const L = Math.max(nameW ? Math.max(112, 14 + nameW + edgeHalf(lo)) : 28, edgeHalf(lo) + 4), R = Math.max(28, edgeHalf(hi) + 4);
    const xs = (v) => L + ((v - lo) / (hi - lo)) * (PLOT_W - L - R);
    // Labels of points and spans sit in rows above the line. The rows are worked out for each line of the scene in
    // order, from the data alone (so any time gives the same picture): a label keeps the row it had on the line before
    // while that row stays clear, otherwise takes the lowest clear row (up to 3 rows), and is kept inside the drawing.
    const ROW = 26, ROWS = 3, GAP = 8;
    const estW = (str) => [...str].reduce((u, ch) => u + (ch === ' ' ? 6 : ch.codePointAt(0) < 0x2e80 ? 12 : 20), 0);
    const marks = [...(b.spans || []).map((o) => ({ o, kind: 'span', cx: (xs(o.from) + xs(o.to)) / 2 })),
                   ...(b.points || []).map((o) => ({ o, kind: 'pt', cx: xs(o.value) }))];
    const labelled = marks.filter((m) => m.o.label != null);
    for (const m of labelled) { m.w = estW(String(m.o.label)); m.x = Math.max(4 + m.w / 2, Math.min(PLOT_W - 4 - m.w / 2, m.cx)); }
    const live = (o, i) => (o.at == null || i >= o.at) && (o.out == null || i < o.out);
    const lastIdx = Math.max(0, ...labelled.flatMap((m) => [m.o.at, m.o.out]).filter((v) => v != null));
    const layouts = [];
    for (let i = 0, prev = new Map(); i <= lastIdx; i++) {
      const rows = new Map(), taken = [];
      const hits = (m, r) => taken.filter((q) => q.r === r && m.x - m.w / 2 < q.x + q.w / 2 + GAP && m.x + m.w / 2 + GAP > q.x - q.w / 2).length;
      const order = labelled.filter((m) => live(m.o, i)).sort((p, q) => (prev.has(p) ? 0 : 1) - (prev.has(q) ? 0 : 1));
      for (const m of order) {
        const tries = [...new Set([prev.get(m), ...Array.from({ length: ROWS }, (_, k) => k)].filter((r) => r != null))];
        let r = tries.find((k) => hits(m, k) === 0);
        if (r == null) r = tries.reduce((best, k) => (hits(m, k) < hits(m, best) ? k : best), tries[0]);
        rows.set(m, r); taken.push({ r, x: m.x, w: m.w });
      }
      layouts.push(rows); prev = rows;
    }
    const used = Math.max(0, ...layouts.flatMap((l) => [...l.values()]));
    const extra = ROW * used, yLine = (sec ? 92 : 62) + extra, H = yLine + (sec ? 48 : 46);
    const count = Math.round((hi - lo) / step), slot = (PLOT_W - L - R) / count;
    // label every N ticks: as written, or the smallest of 1, 2, 5, 10 that keeps the widest label clear of its neighbours
    const widest = Math.max(...Array.from({ length: count + 1 }, (_, i) => { const v = lo + i * step;
      return Math.max(labelW(tickText(v)), sec ? labelW(secText(v)) : 0); }));
    const every = b.label_every || [1, 2, 5, 10].find((k) => k * slot >= widest) || 10;
    const svg = sv('svg', { viewBox: `0 0 ${PLOT_W} ${H}`, width: PLOT_W, height: H, class: 'b-nl', role: 'img', 'aria-label': '数直線' });
    const text = (x, y, str, cls, anchor = 'middle') => { const e = sv('text', { x, y, class: cls, 'text-anchor': anchor }); e.textContent = str; return e; };
    const mainY = sec ? yLine - 18 : yLine + 32, secY = yLine + 36, markY = sec ? yLine - 46 : yLine - 24;
    const draw = (m) => {
      const g = timing(sv('g', { class: m.kind === 'span' ? 'nl-span' : 'nl-pt' }), m.o);
      if (m.kind === 'span') g.append(sv('rect', { x: xs(m.o.from), y: yLine - 8, width: xs(m.o.to) - xs(m.o.from), height: 16, rx: 4 }));
      else g.append(sv('circle', { cx: m.cx, cy: yLine, r: 7 }));
      if (m.o.label != null) { m.lab = text(m.x, markY, String(m.o.label), 'nl-mark'); g.append(m.lab); }
      return g;
    };
    for (const m of marks) if (m.kind === 'span') svg.append(draw(m));
    svg.append(sv('line', { x1: L, x2: PLOT_W - R, y1: yLine, y2: yLine, class: 'nl-axis' }));
    for (let i = 0; i <= count; i++) {
      const v = lo + i * step, x = xs(v), major = i % every === 0;
      svg.append(sv('line', { x1: x, x2: x, y1: yLine - (major ? 10 : 6), y2: yLine + (major ? 10 : 6), class: 'nl-tick' }));
      if (!major) continue;
      svg.append(text(x, mainY, tickText(v), 'nl-num'));
      if (sec) svg.append(text(x, secY, secText(v), 'nl-num nl-sec'));
    }
    if (b.name) svg.append(text(8, mainY, String(b.name), 'nl-name', 'start'));
    if (sec && sec.name) svg.append(text(8, secY, String(sec.name), 'nl-name', 'start'));
    for (const m of marks) if (m.kind === 'pt') svg.append(draw(m));
    svg.__update = (idx) => {
      const rows = layouts[Math.max(0, Math.min(idx, layouts.length - 1))];
      for (const m of labelled) m.lab.setAttribute('y', markY - ROW * (rows.get(m) || 0));
    };
    return svg;
  }
  BLOCKS.numberline = numberlineBlock;

  // ================= chart (bar / line) =================
  // Series take fixed colours by order (--s1, --s2, --s3), never by rank. Thin bars with a 4px rounded end, 3px lines,
  // markers with a ring, hairline grid, one baseline, a legend whenever there are two or more series.
  const niceStep = (raw) => { const e = 10 ** Math.floor(Math.log10(raw)), f = raw / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e; };
  const fmtVal = (v) => Number(v.toFixed(6)).toLocaleString('ja-JP').replace('-', '−');
  function chartBlock(b) {
    const H = b.height || 230, ns = b.series.length, n = b.labels.length, legendH = ns > 1 ? 30 : 0;
    const vals = b.series.flatMap((se) => se.values);
    let lo, hi, stepY;
    if (b.y) { [lo, hi] = b.y; stepY = niceStep((hi - lo) / 4); }
    else {
      lo = Math.min(0, ...vals); hi = Math.max(0, ...vals); if (hi === lo) hi = lo + 1;
      stepY = niceStep((hi - lo) / 4); hi = Math.ceil(hi / stepY) * stepY; lo = Math.floor(lo / stepY) * stepY;
    }
    const tickW = Math.max(...[lo, hi].map((v) => fmtVal(v).length)) * 9 + 14;
    const unitW = b.unit ? [...`(${b.unit})`].reduce((u, ch) => u + (ch.codePointAt(0) < 0x2e80 ? 10 : 16), 0) + 12 : 0;
    const P = { l: Math.max(40, tickW, unitW), r: 16, t: 16 + legendH + (b.unit ? 18 : 0), b: 34 }, iw = PLOT_W - P.l - P.r, ih = H - P.t - P.b;
    const sy = (v) => P.t + ((hi - v) / (hi - lo)) * ih, band = iw / n, cx = (i) => P.l + band * (i + 0.5), base = sy(Math.max(lo, Math.min(hi, 0)));
    const svg = sv('svg', { viewBox: `0 0 ${PLOT_W} ${H}`, width: PLOT_W, height: H, class: 'b-chart', role: 'img', 'aria-label': 'グラフ' });
    const text = (x, y, str, cls, anchor = 'middle') => { const e = sv('text', { x, y, class: cls, 'text-anchor': anchor }); e.textContent = str; return e; };
    for (let v = Math.ceil(lo / stepY - 1e-9) * stepY; v <= hi + 1e-9; v += stepY) {
      svg.append(sv('line', { x1: P.l, x2: P.l + iw, y1: sy(v), y2: sy(v), class: Math.abs(v) < 1e-9 ? 'pl-axis' : 'pl-grid' }));
      svg.append(text(P.l - 8, sy(v) + 5, fmtVal(v), 'pl-tick', 'end'));
    }
    if (lo > 0) svg.append(sv('line', { x1: P.l, x2: P.l + iw, y1: P.t + ih, y2: P.t + ih, class: 'pl-axis' }));
    if (b.unit) svg.append(text(P.l - 8, P.t - 16, `(${b.unit})`, 'pl-tick', 'end'));
    b.labels.forEach((lb, i) => svg.append(text(cx(i), H - 9, String(lb), 'ch-x')));
    const bw = Math.min(36, (band * 0.72 - 2 * (ns - 1)) / ns), gw = bw * ns + 2 * (ns - 1);
    const showVals = b.values ?? (b.kind === 'line' || n * ns <= 12), ends = [];
    b.series.forEach((se, si) => {
      const g = timing(sv('g', { class: `ch-s ch-s${si}` }), se);
      if (b.kind === 'bar') {
        se.values.forEach((v, i) => {
          const x = cx(i) - gw / 2 + si * (bw + 2), y = sy(v), up = y <= base, h = Math.abs(base - y), r = Math.min(4, h, bw / 2);
          const d = up ? `M${x} ${base}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + bw - r}Q${x + bw} ${y} ${x + bw} ${y + r}V${base}Z`
                       : `M${x} ${base}V${y - r}Q${x} ${y} ${x + r} ${y}H${x + bw - r}Q${x + bw} ${y} ${x + bw} ${y - r}V${base}Z`;
          g.append(sv('path', { d, class: 'ch-bar' }));
          if (showVals) g.append(text(x + bw / 2, up ? y - 7 : y + 20, fmtVal(v), 'ch-val'));
        });
      } else {
        const pts = se.values.map((v, i) => [cx(i), sy(v)]);
        g.append(sv('path', { d: pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(''), class: 'ch-line' }));
        for (const [x, y] of pts) g.append(sv('circle', { cx: x, cy: y, r: 5, class: 'ch-dot' }));
        if (showVals) { const [x, y] = pts[pts.length - 1], t = text(x, y - 13, fmtVal(se.values[se.values.length - 1]), 'ch-val'); g.append(t); ends.push({ y, t }); }
      }
      svg.append(g);
    });
    ends.sort((p, q) => p.y - q.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 24) ends[i].t.setAttribute('y', ends[i].y + 24);
    if (ns > 1) {
      let x = P.l;
      b.series.forEach((se, si) => {
        const g = timing(sv('g', { class: `ch-key ch-s${si}` }), se);
        g.append(sv('rect', { x, y: 6, width: 16, height: 16, rx: 4, class: 'ch-bar' }));
        const t = text(x + 24, 20, String(se.name), 'ch-legend', 'start'); g.append(t); svg.append(g);
        x += 24 + [...String(se.name)].reduce((u, ch) => u + (ch.codePointAt(0) < 0x2e80 ? 10 : 18), 0) + 22;
      });
    }
    return svg;
  }
  BLOCKS.chart = chartBlock;

  function sceneEl(sc) {
    const s = el('section', 'scene'); s.dataset.scene = sc.id;
    for (const b of sc.blocks) s.append(timing(BLOCKS[b.type](b), b));
    return s;
  }

  // ================= engines =================
  // Both engines expose: play(), pause(), seek(t), poll() -> t, playing, setRate(r); and call hooks.onPause(point) / hooks.onEnded().
  function AudioEngine(doc, flat, hooks) {
    const bin = atob(doc.audio.data), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([bytes], { type: doc.audio.mime || 'audio/mp4' }));
    const audio = new Audio(); audio.preload = 'auto'; audio.src = url;
    const points = flat.lines.filter((l) => l.pause).map((l) => l.end);
    let t = 0, last = null, dead = false;
    audio.addEventListener('ended', () => { if (dead) return; t = flat.duration; hooks.onEnded(); });
    audio.addEventListener('loadedmetadata', () => { if (Math.abs(audio.currentTime - t) > 0.2) try { audio.currentTime = t; } catch { /* ignore */ } });
    audio.addEventListener('error', () => { if (!dead) hooks.onError('音声を再生できません。この端末が AAC（m4a）に対応していない可能性があります。'); });
    return {
      get playing() { return !audio.paused; },
      play() { last = null; return audio.play().catch(() => hooks.onError('音声の再生が始まりませんでした。もう一度 ▶ を押してください。')); },
      pause() { audio.pause(); t = audio.currentTime; },
      seek(x) { t = x; last = null; try { audio.currentTime = x; } catch { /* metadata not ready */ } },
      setRate(r) { audio.playbackRate = r; },
      poll() {
        if (audio.paused) return t;
        const ct = audio.currentTime;
        const p = last == null ? null : points.find((x) => last < x && x <= ct);
        if (p != null) { audio.pause(); this.seek(p); hooks.onPause(p); return p; }
        last = ct; t = ct; return ct;
      },
      destroy() { dead = true; audio.pause(); audio.removeAttribute('src'); URL.revokeObjectURL(url); },
    };
  }

  // ================= browser voices (draft mode) =================
  // macOS / iOS also list novelty voices (Eddy, Flo, Grandma ...) under ja-JP. Taking the first local voice often lands on one
  // of them, so voices are ranked: neural / premium voices first, novelty voices last. The viewer can override the choice.
  const NOVELTY = /^(Eddy|Flo|Grandma|Grandpa|Reed|Rocko|Sandy|Shelley|Albert|Bad News|Bahh|Bells|Boing|Bubbles|Cellos|Good News|Jester|Organ|Superstar|Trinoids|Whisper|Wobble|Zarvox|Junior|Ralph|Fred|Kathy)\b/i;
  const RANK = [[/Nanami|Keita/i, 60], [/Google/i, 50], [/Hattori/i, 45], [/O-?Ren/i, 35], [/Kyoko/i, 30], [/Otoya/i, 25], [/Ayumi|Haruka|Ichiro|Sayaka/i, 20]];
  const voiceScore = (v) => {
    if (NOVELTY.test(v.name)) return -100;
    let s = 0; for (const [re, p] of RANK) if (re.test(v.name)) { s += p; break; }
    if (/premium|プレミアム|enhanced|拡張|natural|neural|online/i.test(v.name)) s += 15;
    return s;
  };
  const Voices = {
    list() {
      if (!('speechSynthesis' in window)) return [];
      return speechSynthesis.getVoices().filter((v) => /^ja/i.test(v.lang)).sort((a, b) => voiceScore(b) - voiceScore(a) || a.name.localeCompare(b.name));
    },
    chosen() { const all = this.list(); if (!all.length) return null; const uri = store.get('voice'); return all.find((v) => v.voiceURI === uri) || all[0]; },
  };

  function DraftEngine(flat, hooks) {
    const synth = 'speechSynthesis' in window ? window.speechSynthesis : null;
    const lines = flat.lines;
    let playing = false, rate = 1, t = 0, anchorT = 0, anchorAt = 0, limit = 0, token = 0, timer = null;
    const now = () => performance.now();
    const voice = () => (synth ? Voices.chosen() : null);
    function stopInternals() { token++; clearTimeout(timer); if (synth) synth.cancel(); }
    function startLine(i) {
      const ln = lines[i], my = ++token;
      t = anchorT = ln.start; anchorAt = now(); limit = ln.end - 0.02;
      const done = () => { if (my === token) finishLine(i); };
      const v = voice();
      if (synth && v) {
        const u = new SpeechSynthesisUtterance(ln.say); u.lang = 'ja-JP'; u.rate = rate;
        try { u.voice = v; } catch { /* keep the language default */ }
        u.onend = done; u.onerror = () => { if (my === token) timer = setTimeout(done, Math.max(0, (ln.end - t) * 1000 / rate)); };
        synth.speak(u);
      } else timer = setTimeout(done, (ln.end - ln.start) * 1000 / rate); // no voice: silent clock
    }
    function finishLine(i) {
      const ln = lines[i]; t = ln.end;
      if (ln.pause) { playing = false; hooks.onPause(ln.end); return; }
      if (i + 1 >= lines.length) { playing = false; t = flat.duration; hooks.onEnded(); return; }
      const next = lines[i + 1], my = ++token;
      anchorT = ln.end; anchorAt = now(); limit = next.start;
      timer = setTimeout(() => { if (my === token) startLine(i + 1); }, (next.start - ln.end) * 1000 / rate);
    }
    return {
      get playing() { return playing; },
      play() {
        playing = true; stopInternals();
        let i = lastAtOrBefore(lines, t + 0.001);
        if (i >= 0 && t >= lines[i].end - 0.03) i += 1; // between lines: start the next one
        startLine(Math.max(0, Math.min(lines.length - 1, i)));
      },
      pause() { t = this.poll(); playing = false; stopInternals(); },
      seek(x) { const was = playing; stopInternals(); playing = false; t = x; if (was) this.play(); },
      setRate(r) { rate = r; },
      poll() { if (!playing) return t; t = Math.min(anchorT + ((now() - anchorAt) / 1000) * rate, limit); return t; },
      destroy() { playing = false; stopInternals(); },
      get voiceless() { return !voice(); },
    };
  }

  // ================= player =================
  const ui = {
    player: $('player'), stage: $('stage'), viewport: $('viewport'), scenes: $('scenes'), cap: $('caption').firstElementChild,
    seek: $('seek'), time: $('time'), playBtn: $('playBtn'), startBtn: $('startBtn'), think: $('thinkStrip'), end: $('endStrip'),
  };
  let cur = null, raf = 0;
  let speedIdx = Math.max(0, SPEEDS.indexOf(+store.get('speed') || 1));

  function showAlert(title, items) {
    const a = $('alert'); a.textContent = '';
    a.append(el('b', null, title));
    if (items && items.length) { const u = el('ul'); for (const it of items.slice(0, 12)) u.append(el('li', null, it)); if (items.length > 12) u.append(el('li', null, `ほか ${items.length - 12} 件`)); a.append(u); }
    a.hidden = false;
  }

  function unmount() {
    if (!cur) return;
    cancelAnimationFrame(raf); cur.engine.destroy(); cur = null;
    ui.scenes.textContent = ''; $('segs').textContent = ''; $('ticks').textContent = ''; $('tr').textContent = '';
  }

  function mount(doc, opts = {}) {
    const { errors, warnings } = validate(doc);
    if (errors.length) { showAlert(`このカセットは読み込めません（エラー ${errors.length} 件）`, errors); return false; }
    $('alert').hidden = true;
    unmount();
    const flat = flatten(doc);
    const hooks = {
      onPause(p) { render(p); ui.think.hidden = false; updatePlay(); setHash(p); },
      onEnded() { render(flat.duration); ui.end.hidden = false; updatePlay(); },
      onError(msg) { showAlert(msg); updatePlay(); },
    };
    const engine = flat.timed ? AudioEngine(doc, flat, hooks) : DraftEngine(flat, hooks);
    engine.setRate(SPEEDS[speedIdx]);
    for (const ch of doc.chapters) for (const sc of ch.scenes) ui.scenes.append(sceneEl(sc));
    const sceneEls = new Map([...ui.scenes.children].map((e) => [e.dataset.scene, e]));
    cur = { doc, flat, engine, sceneEls, t: 0, curScene: null, curLine: -2, curChapter: -1, capKey: null, started: false, trBtns: [], sceneLines: new Map() };
    for (const l of flat.lines) { if (!cur.sceneLines.has(l.scene)) cur.sceneLines.set(l.scene, []); cur.sceneLines.get(l.scene).push(l); }

    // header, mode, credit
    $('cTitle').textContent = doc.title; $('cKicker').textContent = doc.kicker || '';
    const mode = $('modeChip');
    mode.className = `mode ${flat.timed ? 'audio' : 'draft'}`;
    mode.textContent = flat.timed ? '音声入り' : '下書き・端末の読み上げ';
    $('credit').textContent = flat.timed ? `音声: ${doc.audio.credit || doc.audio.engine?.engine || ''}` : '音声: この端末のブラウザ読み上げ（下書きのため、声と長さは端末によって変わります）';
    document.title = `${doc.title} ・ 学習カセット`;

    // chapter bar + seek ticks
    ui.seek.max = String(flat.duration);
    $('startDur').textContent = (flat.timed ? '' : '約') + fmt(flat.duration);
    for (const c of flat.chapters) {
      const s = el('i'); s.style.setProperty('--w', String(c.end - c.start)); $('segs').append(s);
      if (c.start > 0.5) { const k = el('i'); k.style.left = `${(c.start / flat.duration) * 100}%`; $('ticks').append(k); }
    }
    // transcript
    for (const c of flat.chapters) {
      $('tr').append(el('h3', null, c.title));
      flat.lines.forEach((ln, j) => {
        if (ln.chapter !== c.id) return;
        const b = el('button'); b.type = 'button'; b.append(el('span', null, fmt(ln.start)), document.createTextNode(ln.text));
        if (ln.pause) b.classList.add('pausept');
        b.addEventListener('click', () => seekTo(ln.start + 0.01));
        cur.trBtns[j] = b; $('tr').append(b);
      });
    }
    // sources
    const srcs = $('srcs'); srcs.textContent = ''; cur.srcIndex = new Map();
    (doc.sources || []).forEach((s, i) => {
      cur.srcIndex.set(s.id, i + 1);
      const li = el('li'); li.dataset.src = s.id;
      if (s.url && /^https?:\/\//i.test(String(s.url))) { const a = el('a', null, s.label); a.href = s.url; a.target = '_blank'; a.rel = 'noopener'; li.append(a); } else li.append(document.createTextNode(s.label));
      if (s.note) li.append(el('small', null, s.note));
      srcs.append(li);
    });
    if (!srcs.children.length) srcs.append(el('li', null, '出典の記載がありません'));
    // info
    const info = $('info'); info.textContent = '';
    const rows = [['形式', `${doc.format} v${doc.version}`], ['状態', flat.timed ? '音声入り' : '下書き（音声なし）'], ['長さ', `${flat.timed ? '' : '約 '}${flat.duration.toFixed(1)} 秒`],
      ['構成', `${flat.chapters.length} 章 / ${flat.scenes.length} シーン / ${flat.lines.length} 行`]];
    if (flat.timed && doc.audio.engine) rows.push(['音声エンジン', `${doc.audio.engine.engine} ${doc.audio.engine.version}（${doc.audio.engine.voice}）`]);
    if (doc.build) rows.push(['ビルド', `${doc.build.tool} / BudouX ${doc.build.budoux}`], ['内容の指紋', doc.build.content_hash]);
    if (doc.build && doc.build.pcm_sha) rows.push(['音声（圧縮前）', doc.build.pcm_sha], ['ffmpeg', doc.build.ffmpeg || '不明']);
    for (const [k, v] of rows) info.append(el('dt', null, k), el('dd', null, v));
    const warns = $('warns'); warns.textContent = ''; for (const w of warnings) warns.append(el('li', null, `警告: ${w}`));

    fillVoices();
    $('empty').hidden = true; ui.player.hidden = false; $('below').hidden = false;
    ui.startBtn.hidden = false; ui.think.hidden = true; ui.end.hidden = true;
    document.querySelectorAll('#samples button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.id === doc.id)));
    fit();
    const m = /^#t=?(\d+(?:\.\d+)?)$/.exec(opts.hash || '');
    if (m) seekTo(+m[1]); else render(0);
    updatePlay();
    return true;
  }

  function render(x) {
    const c = cur, { lines, scenes, chapters, duration } = c.flat;
    const t = c.t = Math.max(0, Math.min(duration, x));
    const li = lastAtOrBefore(lines, t), line = li >= 0 ? lines[li] : null;
    const si = Math.max(0, lastAtOrBefore(scenes, t)), sc = scenes[si], se = c.sceneEls.get(sc.id);
    if (c.curScene !== sc.id) {
      for (const [id, e] of c.sceneEls) e.classList.toggle('active', id === sc.id);
      c.curScene = sc.id;
      const nums = sc.sources.map((s) => c.srcIndex.get(s)).filter(Boolean);
      $('srcNow').textContent = nums.length ? `出典 ${nums.join('・')}` : '';
      for (const li2 of $('srcs').children) li2.classList.toggle('now', sc.sources.includes(li2.dataset.src));
    }
    const idx = line && line.scene === sc.id ? line.idx : -1;
    const timedEls = se.querySelectorAll('[data-at]');
    for (const e of timedEls) { const at = +e.dataset.at, out = e.dataset.out != null ? +e.dataset.out : Infinity; e.classList.toggle('on', idx >= at && idx < out); }
    for (const e of se.querySelectorAll('[data-out]:not([data-at])')) e.classList.toggle('gone', idx >= +e.dataset.out);
    const focusEls = [...se.querySelectorAll('[data-focus]')];
    const visible = (e) => !e.dataset.at || e.classList.contains('on');
    let any = false;
    for (const e of focusEls) { const f = e.dataset.focus; const on = visible(e) && f !== '' && f.split(',').map(Number).includes(idx); e.classList.toggle('focus', on); any ||= on; }
    for (const e of focusEls) e.classList.toggle('dim', any && visible(e) && !e.classList.contains('focus'));
    const sl = c.sceneLines.get(sc.id) || [];
    for (const pl of se.querySelectorAll('svg.b-plot, svg.b-nl')) pl.__update(idx, t, (i) => (sl[i] ? sl[i].start : 0));
    // caption (BudouX chunks joined with <wbr>, built with DOM nodes only)
    let key = '';
    if (line) { const nextStart = lines[li + 1]?.start ?? duration; if (t < line.end + Math.min(0.6, nextStart - line.end)) key = String(li); }
    if (key !== c.capKey) {
      ui.cap.textContent = '';
      if (key) { const ln = lines[+key]; (ln.chunks && ln.chunks.length ? ln.chunks : [ln.text]).forEach((ch, i) => { if (i) ui.cap.append(document.createElement('wbr')); ui.cap.append(document.createTextNode(ch)); }); }
      c.capKey = key;
    }
    const ci = Math.max(0, lastAtOrBefore(chapters, t));
    if (ci !== c.curChapter) { c.curChapter = ci; const n = $('chName'); n.textContent = ''; n.append(el('b', null, `${ci + 1}/${chapters.length}`), document.createTextNode(chapters[ci].title)); }
    [...$('segs').children].forEach((s, i) => s.style.setProperty('--f', String(i < ci ? 1 : i > ci ? 0 : clamp01((t - chapters[i].start) / (chapters[i].end - chapters[i].start)))));
    if (document.activeElement !== ui.seek) ui.seek.value = String(t);
    ui.time.textContent = `${fmt(t)} / ${fmt(duration)}`;
    if (li !== c.curLine) { c.trBtns[c.curLine]?.classList.remove('now'); c.trBtns[li]?.classList.add('now'); c.curLine = li; }
  }

  function loop() { if (!cur || !cur.engine.playing) { updatePlay(); return; } render(cur.engine.poll()); raf = requestAnimationFrame(loop); }
  function updatePlay() { ui.playBtn.textContent = cur && cur.engine.playing ? '❚❚' : '▶'; }
  function play() {
    if (!cur) return;
    cur.started = true; ui.startBtn.hidden = true; ui.think.hidden = true; ui.end.hidden = true; $('alert').hidden = true;
    if (cur.t >= cur.flat.duration - 0.05) seekTo(0);
    if (!cur.flat.timed && cur.engine.voiceless) showAlert('この端末では日本語の読み上げ音声が見つかりません。画面と字幕だけで進めます。');
    cur.engine.play(); updatePlay(); cancelAnimationFrame(raf); raf = requestAnimationFrame(loop);
  }
  function pause() { if (!cur) return; cur.engine.pause(); render(cur.engine.poll()); updatePlay(); setHash(cur.t); }
  const toggle = () => { if (!cur) return; if (cur.engine.playing) pause(); else play(); };
  function seekTo(x) {
    if (!cur) return;
    x = Math.max(0, Math.min(cur.flat.duration, x));
    ui.think.hidden = true; ui.end.hidden = true; if (x > 0.05) ui.startBtn.hidden = true;
    cur.engine.seek(x); render(x);
  }
  function setHash(t) { try { history.replaceState(null, '', `#t${t.toFixed(1)}`); } catch { /* sandboxed */ } }

  ui.playBtn.addEventListener('click', toggle);
  ui.startBtn.addEventListener('click', play);
  $('thinkBtn').addEventListener('click', play);
  $('againBtn').addEventListener('click', () => { seekTo(0); play(); });
  ui.viewport.addEventListener('click', (e) => { if (!e.target.closest('button')) toggle(); });
  ui.seek.addEventListener('input', () => seekTo(+ui.seek.value));
  const lineStep = (d) => { const L = cur.flat.lines, i = lastAtOrBefore(L, cur.t + 0.05);
    const j = Math.max(0, Math.min(L.length - 1, d < 0 && i >= 0 && cur.t - L[i].start > 1.2 ? i : i + d)); seekTo(L[j].start + 0.01); };
  const chapterStep = (d) => { const C = cur.flat.chapters, i = Math.max(0, lastAtOrBefore(C, cur.t + 0.05)); seekTo(C[Math.max(0, Math.min(C.length - 1, i + d))].start + 0.01); };
  document.addEventListener('keydown', (e) => {
    if (!cur || e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = e.target.tagName;
    if (e.key === ' ' && !['BUTTON', 'INPUT', 'SUMMARY', 'A'].includes(tag)) { e.preventDefault(); toggle(); }
    else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && tag !== 'INPUT') { e.preventDefault(); const d = e.key === 'ArrowRight' ? 1 : -1; if (e.shiftKey) chapterStep(d); else lineStep(d); }
  });

  // preferences
  const setSpeed = (i) => { speedIdx = (i + SPEEDS.length) % SPEEDS.length; $('speedBtn').textContent = `${SPEEDS[speedIdx]}×`; store.set('speed', SPEEDS[speedIdx]);
    if (cur) { const was = cur.engine.playing; cur.engine.setRate(SPEEDS[speedIdx]); if (was && !cur.flat.timed) { cur.engine.pause(); cur.engine.play(); } } };
  setSpeed(speedIdx);
  $('speedBtn').addEventListener('click', () => setSpeed(speedIdx + 1));
  // voice picker (draft cassettes only). Voices can arrive after load, so the list is rebuilt on voiceschanged.
  function fillVoices() {
    const sel = $('voiceSel'), all = Voices.list();
    sel.textContent = '';
    if (!cur || cur.flat.timed || !all.length) { sel.hidden = true; return; }
    const chosen = Voices.chosen();
    all.forEach((v, i) => {
      const tag = voiceScore(v) < 0 ? '（品質低め）' : i === 0 ? '（おすすめ）' : '';
      const o = el('option', null, `${v.name}${tag}`); o.value = v.voiceURI; o.selected = v === chosen; sel.append(o);
    });
    sel.hidden = false;
  }
  $('voiceSel').addEventListener('change', (e) => {
    store.set('voice', e.target.value);
    if (cur && !cur.flat.timed && cur.engine.playing) { cur.engine.pause(); cur.engine.play(); }
  });
  if ('speechSynthesis' in window) {
    if (speechSynthesis.addEventListener) speechSynthesis.addEventListener('voiceschanged', fillVoices);
    else speechSynthesis.onvoiceschanged = fillVoices;
  }
  const setCC = (on) => { ui.player.classList.toggle('nocap', !on); $('ccBtn').setAttribute('aria-pressed', String(on)); store.set('cc', on); };
  setCC(store.get('cc') !== false);
  $('ccBtn').addEventListener('click', () => setCC(ui.player.classList.contains('nocap')));

  // stage scaling
  const fit = () => { const w = ui.viewport.getBoundingClientRect().width; if (w) ui.stage.style.setProperty('--scale', String(w / 720)); };
  new ResizeObserver(fit).observe(ui.viewport);

  // ================= loading =================
  function loadText(text, name) {
    let doc;
    try { doc = JSON.parse(text); } catch (err) { showAlert(`${name} は JSON として読めません`, [String(err.message || err)]); return; }
    mount(doc);
  }
  function loadFile(file) {
    if (!file) return;
    if (file.size > 40 * 1024 * 1024) { showAlert(`${file.name} は大きすぎます（40MB まで）`); return; }
    const r = new FileReader();
    r.onload = () => loadText(String(r.result), file.name);
    r.onerror = () => showAlert(`${file.name} を読めませんでした`);
    r.readAsText(file, 'utf-8');
  }
  $('fileIn').addEventListener('change', (e) => { loadFile(e.target.files[0]); e.target.value = ''; });
  let dragDepth = 0;
  addEventListener('dragenter', (e) => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { dragDepth++; $('drop').hidden = false; } });
  addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('drop').hidden = true; });
  addEventListener('dragover', (e) => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });
  addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; $('drop').hidden = true; loadFile(e.dataTransfer?.files?.[0]); });

  // bundled samples (filled in by tools/build_player.py; may be empty)
  let bundled = [];
  try { bundled = JSON.parse($('bundled')?.textContent || '[]'); } catch { bundled = []; }
  if (bundled.length) {
    const box = $('samples'); box.append(document.createTextNode('サンプル:'));
    for (const doc of bundled) {
      const b = el('button', null, doc.title); b.type = 'button'; b.dataset.id = doc.id;
      b.addEventListener('click', () => mount(doc)); box.append(b);
    }
    mount(bundled[0], { hash: location.hash });
  }
  // lines() and seek() are for tools/qa.py (screen checks); playback never uses them.
  window.LessonCassette = {
    load: (doc) => mount(doc), validate,
    lines: () => (cur ? cur.flat.lines.map(({ scene, idx, start, end }) => ({ scene, idx, start, end })) : []),
    seek: (t) => seekTo(t),
  };
})();
