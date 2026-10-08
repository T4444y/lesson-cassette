"""音声合成エンジンの差し替え口。

どのエンジンも「名前・版・声の識別子」と synthesize(text) -> (float配列, サンプルレート) を持つ。
キャッシュのキーにはこの 3 つ（＋声のモデルファイルのハッシュ）が入るので、
エンジンや声を変えると自動的に作り直され、変えなければ前回の音声がそのまま使われる。

採用しているのは Open JTalk だけ（2026-10-06 決定。経緯は README の「声について」）。
別のエンジンを足すときは、同じ形のクラスを書いて ENGINES に登録する。
"""
import hashlib
import os


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OpenJTalkEngine:
    """Open JTalk（pyopenjtalk）。本体 MIT / 修正BSD、声「Mei」は CC BY 3.0。乱数を使わないので毎回同じ波形になる。"""

    name = "openjtalk"

    def __init__(self, speed=1.0, half_tone=0.0):
        import pyopenjtalk

        self._pjt = pyopenjtalk
        self.version = pyopenjtalk.__version__
        voice = os.path.join(os.path.dirname(pyopenjtalk.__file__), "htsvoice", "mei_normal.htsvoice")
        self.voice = "mei_normal"
        self.voice_sha = _sha256_file(voice)[:16]
        self.params = {"speed": speed, "half_tone": half_tone}
        self.credit = 'Open JTalk / HTS Voice "Mei" (c) Nagoya Institute of Technology, CC BY 3.0'

    def fingerprint(self):
        return {"engine": self.name, "version": self.version, "voice": self.voice,
                "voice_sha": self.voice_sha, "params": self.params}

    def synthesize(self, text):
        x, sr = self._pjt.tts(text, **self.params)
        return x, sr


ENGINES = {"openjtalk": OpenJTalkEngine}
