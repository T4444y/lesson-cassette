#!/usr/bin/env python3
"""Python の検証（tools/cassette.py）と、プレイヤーの検証（player/player.js）が同じ結果を返すかを確かめる。

    python3 tools/check_parity.py                 # lessons/*.yaml と tests/fixtures/*.yaml
    python3 tools/check_parity.py a.yaml b.json   # 指定したファイル

エラー・警告の文言が 1 つでも違えば、違いを表示して終了コード 1 を返す。
Chromium（Playwright）が必要。
"""
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cassette  # noqa: E402


def main():
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "lessons", "*.yaml")) + glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.yaml")))
    docs = [(os.path.relpath(p, ROOT), cassette.load(p)) for p in paths]
    from playwright.sync_api import sync_playwright
    tmp = tempfile.mkdtemp(prefix="parity-")
    subprocess.run([sys.executable, os.path.join(HERE, "build_player.py"), "--out", tmp], check=True, capture_output=True)
    bad = 0
    with sync_playwright() as p:
        browser = None
        for exe in (None, os.environ.get("CHROMIUM_PATH")):
            try:
                browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            sys.exit("Chromium を起動できません")
        pg = browser.new_page()
        pg.goto("file://" + os.path.join(tmp, "player.html"))
        for name, doc in docs:
            pe, pw = cassette.validate(doc)
            js = pg.evaluate("(d) => window.LessonCassette.validate(d)", json.loads(json.dumps(doc, default=str)))
            diffs = []
            for kind, a, b in (("エラー", pe, js["errors"]), ("警告", pw, js["warnings"])):
                for m in a:
                    if m not in b:
                        diffs.append(f"  {kind} Python だけ: {m}")
                for m in b:
                    if m not in a:
                        diffs.append(f"  {kind} JS だけ:     {m}")
            print(f"{'一致' if not diffs else '不一致'}  {name}（エラー {len(pe)}・警告 {len(pw)}）")
            for d in diffs:
                print(d)
            bad += bool(diffs)
        browser.close()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
