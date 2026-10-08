#!/usr/bin/env python3
"""qa.py が、わざと誤りを入れた台本（tests/fixtures/qa-checks*.yaml）の誤りを拾うかを確かめる。

    python3 tests/test_qa.py      # pytest でも動く

画面のチェックを含むので Chromium（Playwright）が必要。
"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (台本, 要対応に含まれるべき文, 要確認に含まれるべき文, どちらにも出てはいけない文)
CASES = [
    ("qa-checks", [
        "mx-unit-wrong table[0]: 分速80m × 3分 は 240m ですが、表は 250 です",
        "mx-num-wrong table[0]: 80 × 3 は 240 ですが、表は 250 です",
        "mx-plus-wrong table[0]: 10 + 2 は 12 ですが、表は 13 です",
        "mx-wordy table[0]: 時速4km × 2時間 は 8000m ですが、表は 9km です",
        "cv-speed-wrong table[0] 行0: 同じ大きさになっていません",
        "cv-pct-wrong table[0] 行1: 同じ大きさになっていません",
        "cv-len-wrong table[0] 行0: 同じ大きさになっていません",
        "cv-time-wrong table[0] 行0: 同じ大きさになっていません",
        "nl-wrong numberline[0] 点0:",
        "nl-wrong numberline[0] 点1:",
        "cell-over#0: 表のセルtd「123456789012」が列の幅に収まらない",
    ], [
        "cell-over table[0] 行0:",
        "nl-crowd#0: 図の文字",
        "plot-overlap#0: グラフのラベル「1時間で進む」",
        "棒グラフの最小値が 0 ではありません",
    ], ["cv-speed-wrong table[0] 行1", "cv-pct-wrong table[0] 行0", "cv-len-wrong table[0] 行1", "nl-wrong numberline[0] 点2"]),
    ("qa-checks-2", [
        "mx-colunit-rownum table[0]: 80 × 3 は 240 ですが、表は 250 です",
        "nl-de numberline[0] 点0:",
        "nl-de numberline[0] 点1:",
        "nl-de numberline[0] 点2:",
        "nl-frac numberline[0] 点0:",
    ], [
        "mx-rowunit-colnum table[0]:",
    ], ["cv-headunit-ok", "cv-headunit-ok2"]),
]


def sections(report):
    must = re.search(r"## 要対応.*?\n(.*?)\n## ", report, re.S).group(1)
    maybe = re.search(r"## 要確認.*?\n(.*?)\n## ", report, re.S).group(1)
    return must, maybe


def run(name):
    out = tempfile.mkdtemp(prefix="qa-test-")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "qa.py"), os.path.join(ROOT, "tests", "fixtures", f"{name}.yaml"), "--out", out],
                   capture_output=True)
    with open(os.path.join(out, name, "report.md"), encoding="utf-8") as f:
        return sections(f.read())


def test_fixtures():
    failed = []
    for name, want_must, want_maybe, never in CASES:
        must, maybe = run(name)
        failed += [f"{name}: 要対応にない「{w}」" for w in want_must if w not in must]
        failed += [f"{name}: 要確認にない「{w}」" for w in want_maybe if w not in maybe]
        failed += [f"{name}: 出てはいけない「{w}」が出た" for w in never if w in must or w in maybe]
    assert not failed, "\n".join(failed)


if __name__ == "__main__":
    try:
        test_fixtures()
    except AssertionError as e:
        print("失敗\n" + str(e))
        sys.exit(1)
    print("すべて通りました")
