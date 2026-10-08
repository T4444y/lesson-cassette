#!/usr/bin/env python3
"""プレイヤーを 1 ファイルの HTML に組み立てる。

  python3 tools/build_player.py                                   # dist/player.html（空のプレイヤー）
  python3 tools/build_player.py --bundle dist/a.cassette.json ... --name player-demo   # サンプル同梱版

--fragment を付けると <!doctype>/<head>/<body> を省いた版も出す（ほかのページに埋め込む用）。
"""
import argparse
import hashlib
import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLE = "学習カセットプレイヤー"


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", nargs="*", default=[], help="同梱するカセット（最初のものを起動時に読み込む）")
    ap.add_argument("--name", default="player")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    ap.add_argument("--fragment", action="store_true")
    a = ap.parse_args()

    docs = []
    for p in a.bundle:
        with open(p, encoding="utf-8") as f:
            docs.append(json.load(f))
    bundled = json.dumps(docs, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")  # no "<" can end or open a tag inside the script
    css, js, shell = read("player", "player.css"), read("player", "player.js"), read("player", "shell.html")
    body = f'{shell}<script type="application/json" id="bundled">{bundled}</script>\n<script>\n{js}</script>\n'
    head = f"<title>{html.escape(TITLE)}</title>\n<style>\n{css}</style>\n"
    standalone = ('<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                  f"{head}</head>\n<body>\n{body}</body>\n</html>\n")
    os.makedirs(a.out, exist_ok=True)
    outs = {f"{a.name}.html": standalone}
    if a.fragment:
        outs[f"{a.name}.fragment.html"] = head + body
    for name, text in outs.items():
        path = os.path.join(a.out, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"{path}  {len(text.encode()) // 1024}KB  sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]}  同梱 {len(docs)} 本")


if __name__ == "__main__":
    main()
