> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/ja.md)

TextEncodeAceStepAudio1.5ノードは、AceStepAudio 1.5モデルで使用するためのテキストおよびオーディオ関連のメタデータを準備します。記述的なタグ、歌詞、音楽パラメータを受け取り、CLIPモデルを使用してオーディオ生成に適したコンディショニング形式に変換します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | はい | N/A | 入力テキストをトークン化およびエンコードするために使用されるCLIPモデルです。 |
| `tags` | STRING | はい | N/A | ジャンル、ムード、楽器など、オーディオの記述的なタグです。複数行入力と動的プロンプトをサポートします。 |
| `lyrics` | STRING | はい | N/A | オーディオトラックの歌詞です。複数行入力と動的プロンプトをサポートします。 |
| `seed` | INT | いいえ | 0 から 18446744073709551615 | 再現可能な生成のためのランダムシード値です。control_after_generateウィジェットを持ちます。デフォルト: 0。 |
| `bpm` | INT | いいえ | 10 から 300 | 生成されるオーディオの1分あたりのビート数（BPM）です。デフォルト: 120。 |
| `duration` | FLOAT | いいえ | 0.0 から 2000.0 | オーディオの希望する長さ（秒単位）です。デフォルト: 120.0。 |
| `timesignature` | COMBO | いいえ | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | 音楽の拍子記号です。 |
| `language` | COMBO | いいえ | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | 入力テキストの言語です。 |
| `keyscale` | COMBO | いいえ | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | 音楽のキーとスケール（メジャーまたはマイナー）です。 |
| `generate_audio_codes` | BOOLEAN | いいえ | N/A | オーディオコードを生成するLLMを有効にします。これは遅くなる可能性がありますが、生成されるオーディオの品質を向上させます。モデルにオーディオリファレンスを与える場合はこれをオフにしてください。デフォルト: True。 |
| `cfg_scale` | FLOAT | いいえ | 0.0 から 100.0 | 分類器なしガイダンススケールです。値が高いほど、出力がプロンプトに密接に従うようになります。デフォルト: 2.0。 |
| `temperature` | FLOAT | いいえ | 0.0 から 2.0 | サンプリング温度です。値が低いほど、出力がより決定的になります。デフォルト: 0.85。 |
| `top_p` | FLOAT | いいえ | 0.0 から 2000.0 | 核サンプリング確率（top-p）です。デフォルト: 0.9。 |
| `top_k` | INT | いいえ | 0 から 100 | 考慮する最高確率トークンの数（top-k）です。デフォルト: 0。 |

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | AceStepAudio 1.5モデルのための、エンコードされたテキストとオーディオパラメータを含むコンディショニングデータです。 |
