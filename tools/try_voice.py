#!/usr/bin/env python3
"""読み上げの試し聞き用。台本の最初の数行だけを合成して samples/ に WAV で保存する。

  python3 tools/try_voice.py lessons/my-topic.yaml --lines 5

カセットは作らない。読み間違いを見つけたら台本の行に say を書いて直す。
"""
import argparse
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cassette  # noqa: E402
from engines import ENGINES  # noqa: E402
from build_cassette import apply_readings, load_readings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lesson")
    ap.add_argument("--engine", default="openjtalk", choices=sorted(ENGINES))
    ap.add_argument("--lines", type=int, default=3)
    ap.add_argument("--out", default="samples")
    a = ap.parse_args()

    doc = cassette.load(a.lesson)
    lines = [ln for ch in doc["chapters"] for sc in ch["scenes"] for ln in sc["lines"]][: a.lines]
    t0 = time.time()
    engine = ENGINES[a.engine]()
    print(f"{a.engine}: 準備 {time.time() - t0:.1f} 秒 / {engine.credit}")
    os.makedirs(a.out, exist_ok=True)
    readings, _ = load_readings()
    for i, ln in enumerate(lines):
        say = apply_readings(ln.get("say") or ln["text"], readings)
        t1 = time.time()
        x, sr = engine.synthesize(say)
        pcm = np.clip(np.round(x), -32768, 32767).astype("<i2")
        path = os.path.join(a.out, f"{a.engine}-{i + 1:02d}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr), w.writeframes(pcm.tobytes())
        dur = len(pcm) / sr
        print(f"  {path}  音声 {dur:.1f} 秒 / 合成 {time.time() - t1:.1f} 秒  「{ln['text']}」")


if __name__ == "__main__":
    main()
