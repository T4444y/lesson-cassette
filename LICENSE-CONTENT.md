# 教材（台本・カセット・文書）のライセンス

このリポジトリは、中身によってライセンスが分かれています。

| 対象 | ライセンス |
|---|---|
| コード：`tools/`・`player/`・`tests/`・`lessons/*.verify.py`（検算スクリプト）・`dist/player.html` | MIT（`LICENSE`） |
| 教材と文書：`lessons/*.yaml`（台本）・`dist/*.cassette.json` の文字と画面の内容・`SPEC.md`・`AUTHORING.md`・`README.md`・`docs/` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)（クリエイティブ・コモンズ 表示 4.0 国際） |
| `dist/*.cassette.json` に入っている音声 | 下の「音声について」を参照 |

CC BY 4.0 の表示は、たとえば次のように書いてください。

> 「学習カセット」T4444y（https://github.com/T4444y/lesson-cassette）、CC BY 4.0

## 音声について

`dist/*.cassette.json` の音声は、Open JTalk と HTS Voice「Mei」で合成したものです。

- 声「Mei」：© Nagoya Institute of Technology（配布：MMDAgent Project）、[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)
- カセットを配ったり使ったりするときは、このクレジットを残してください。カセットの `audio.credit` に書いてあり、プレイヤーにも表示されます
- 音声の文面（台本）は、上の表のとおり CC BY 4.0 です

## 出典について

サンプルの台本の事実は、各カセットの `sources` に書いた資料で確かめています。資料の文章は書き写さず、要点を自分の言葉で説明しています。出典の資料そのものは、それぞれの権利者のものです。
