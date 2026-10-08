#!/usr/bin/env python3
"""台本（YAML か JSON）を検証し、学習カセット（.cassette.json）にする。

  python3 tools/build_cassette.py lessons/how-it-works.yaml            # 音声入り
  python3 tools/build_cassette.py lessons/my-topic.yaml --draft        # 下書き（音声なし）

音声は行ごとに cache/ に保存する。キーは「読み上げ文＋エンジン＋声＋版」のハッシュなので、
台詞を 1 行直しても合成し直すのはその行だけ。同じ入力なら出力は毎回同じバイト列になる。
"""
import argparse
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cassette  # noqa: E402

TOOL = "build_cassette 1.3"


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def r3(x):
    return round(float(x), 3)


def iter_lines(doc):
    for ch in doc["chapters"]:
        for sc in ch["scenes"]:
            for i, ln in enumerate(sc["lines"]):
                yield ch, sc, i, ln


def add_chunks(doc):
    import budoux
    parser = budoux.load_default_japanese_parser()
    for _, _, _, ln in iter_lines(doc):
        ln["chunks"] = parser.parse(ln["text"])


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_readings(path=os.path.join(ROOT, "readings.yaml"), local=os.path.join(ROOT, "readings.local.yaml")):
    """読み辞書（語 → 読み）と、readings.yaml の指紋。ファイルがなければ空。
    readings.local.yaml（個人の固有名詞など。リポジトリには入れない）があれば、あとから重ねる。
    指紋は readings.yaml だけで取る（共有の辞書が同じかを確かめるため）。"""
    import yaml
    table, sha = {}, None
    for p in (path, local):
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            raw = f.read()
        table.update({str(k): str(v) for k, v in (yaml.safe_load(raw) or {}).items()})
        if p == path:
            sha = sha256(raw.encode())[:8]
    return table, sha


# 1 文字の単位は、Open JTalk が読まない（80m → ハチジュー）。数字の直後にあるときだけ読みを補う（km・cm・kg・mL などは読める）
UNIT_READINGS = {"m": "メートル", "g": "グラム", "L": "リットル"}


def apply_readings(text, readings):
    import re
    for word in sorted(readings, key=len, reverse=True):
        text = re.sub(re.escape(word), readings[word], text, flags=re.IGNORECASE)
    return re.sub(r"(?<=[0-9０-９])([mgL])(?![A-Za-z])", lambda m: UNIT_READINGS[m.group(1)], text)


def synthesize(doc, engine, cache_dir, readings=None):
    import numpy as np
    os.makedirs(cache_dir, exist_ok=True)
    fp, hits, made, wavs = engine.fingerprint(), 0, 0, []
    for _, _, _, ln in iter_lines(doc):
        say = apply_readings(ln.get("say") or ln["text"], readings or {})
        key = sha256(json.dumps({"say": say, **fp}, sort_keys=True, ensure_ascii=False).encode())[:24]
        path = os.path.join(cache_dir, f"{key}.wav")
        if os.path.exists(path):
            hits += 1
        else:
            x, sr = engine.synthesize(say)
            pcm = np.clip(np.round(x), -32768, 32767).astype("<i2")
            with wave.open(path, "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr), w.writeframes(pcm.tobytes())
            made += 1
        wavs.append(path)
    return wavs, hits, made


def read_wav(path):
    import numpy as np
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"), w.getframerate()


def lay_out(doc, wavs):
    """各行の start / end を決め、無音を挟んで 1 本の波形にする。"""
    import numpy as np
    tm = {**cassette.TIMING_DEFAULTS, **(doc.get("timing") or {})}
    sr = read_wav(wavs[0])[1]
    pieces, n, prev = [], 0, None

    def push(arr):
        nonlocal n
        pieces.append(arr)
        n += len(arr)

    silence = lambda sec: np.zeros(int(round(sec * sr)), dtype="<i2")
    push(silence(tm["lead_in"]))
    for (ch, sc, i, ln), path in zip(iter_lines(doc), wavs):
        if prev is not None:
            gap = tm["gap"]
            if i == 0:
                gap = max(gap, tm["scene_gap"])
            if prev.get("pause"):
                gap = max(gap, tm["pause_gap"])
            push(silence(gap))
        pcm, _ = read_wav(path)
        ln["start"] = r3(n / sr)
        push(pcm)
        ln["end"] = r3(n / sr)
        prev = ln
    push(silence(0.8))
    return np.concatenate(pieces), sr, r3(n / sr)


def encode_aac(pcm, sr, bitrate="48k"):
    with tempfile.TemporaryDirectory() as td:
        src, dst = os.path.join(td, "a.wav"), os.path.join(td, "a.m4a")
        with wave.open(src, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr), w.writeframes(pcm.tobytes())
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "24000",
                        "-c:a", "aac", "-b:a", bitrate, "-map_metadata", "-1", "-fflags", "+bitexact",
                        "-flags:a", "+bitexact", "-movflags", "+faststart", dst], check=True)
        return open(dst, "rb").read()


def build(src_path, draft, engine_name, cache_dir):
    doc = cassette.load(src_path)
    errs, warns = cassette.validate(doc)
    for w in warns:
        print("  [警告]", w)
    if errs:
        for e in errs:
            print("  [エラー]", e)
        raise SystemExit(f"{src_path}: エラーが {len(errs)} 件あるためビルドを中止しました")
    doc = copy.deepcopy(doc)
    for k in cassette.BUILD_ONLY:
        doc.pop(k, None)
    for _, _, _, ln in iter_lines(doc):
        for k in ("chunks", "start", "end"):
            ln.pop(k, None)
    add_chunks(doc)
    budoux_ver = metadata.version("budoux")
    note, pcm_sha, ffmpeg_ver = "", None, None
    readings, readings_sha = load_readings()
    if readings:
        # 下書き（ブラウザ読み上げ）でも同じ読みになるよう、辞書で変わる行には say を書き込む
        for _, _, _, ln in iter_lines(doc):
            base = ln.get("say") or ln["text"]
            fixed = apply_readings(base, readings)
            if fixed != base:
                ln["say"] = fixed
    if not draft:
        from engines import ENGINES
        engine = ENGINES[engine_name]()
        wavs, hits, made = synthesize(doc, engine, cache_dir, readings)
        pcm, sr, duration = lay_out(doc, wavs)
        pcm_sha = sha256(pcm.tobytes())[:16]  # 圧縮前の音声。マシンが違っても一致するはずの指紋
        m4a = encode_aac(pcm, sr)
        ffmpeg_ver = ffmpeg_version()
        doc["duration"] = duration
        doc["audio"] = {"mime": "audio/mp4", "engine": engine.fingerprint(), "credit": engine.credit,
                        "data": base64.b64encode(m4a).decode()}
        note = f"音声 {len(m4a) // 1024}KB・{duration:.1f}秒（キャッシュ {hits} / 新規合成 {made}）"
    # 内容の指紋：圧縮後の音声バイト列（ffmpeg の版で変わる）を除き、圧縮前の音声の指紋を足して計算する
    body = copy.deepcopy(doc)
    if "audio" in body:
        body["audio"].pop("data", None)
    content_hash = sha256(json.dumps(body, ensure_ascii=False).encode() + (pcm_sha or "").encode())[:12]
    doc["build"] = {"tool": TOOL, "budoux": budoux_ver, "draft": draft, "content_hash": content_hash}
    if readings_sha:
        doc["build"]["readings"] = readings_sha
    if pcm_sha:
        doc["build"].update({"pcm_sha": pcm_sha, "ffmpeg": ffmpeg_ver})
    return doc, note


def ffmpeg_version():
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
    parts = out.split()
    return parts[2] if len(parts) > 2 else out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--draft", action="store_true", help="音声を作らず下書きカセットにする")
    ap.add_argument("--engine", default="openjtalk")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--cache", default="cache")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for src in a.sources:
        doc, note = build(src, a.draft, a.engine, a.cache)
        out = os.path.join(a.out, f'{doc["id"]}.cassette.json')
        text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        kind = "下書き" if a.draft else "音声入り"
        b = doc["build"]
        print(f"{out}  [{kind}] {len(text.encode()) // 1024}KB  {note}")
        print(f"  内容 {b['content_hash']}" + (f"  音声（圧縮前）{b['pcm_sha']}  ffmpeg {b['ffmpeg']}" if b.get("pcm_sha") else "")
              + f"  ファイル sha256 {sha256(text.encode())[:16]}")


if __name__ == "__main__":
    main()
