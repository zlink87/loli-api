> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WanInfiniteTalkToVideo/ja.md)

WanInfiniteTalkToVideoノードは、音声入力から動画シーケンスを生成します。このノードは、1人または2人の話者から抽出された音声特徴量を条件付けとして使用するビデオ拡散モデルを利用し、話し手の動画の潜在表現を生成します。既存のシーケンスを拡張する場合、モーションコンテキストとして前のフレームを使用することができます。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `mode` | COMBO | はい | `"single_speaker"`<br>`"two_speakers"` | 音声入力モードです。`"single_speaker"`は1つの音声入力を使用します。`"two_speakers"`は2人目の話者と対応するマスクの入力を有効にします。 |
| `model` | MODEL | はい | - | ベースとなるビデオ拡散モデルです。 |
| `model_patch` | MODELPATCH | はい | - | 音声投影レイヤーを含むモデルパッチです。 |
| `positive` | CONDITIONING | はい | - | 生成を導くためのポジティブな条件付けです。 |
| `negative` | CONDITIONING | はい | - | 生成を導くためのネガティブな条件付けです。 |
| `vae` | VAE | はい | - | 画像を潜在空間にエンコード/デコードするために使用されるVAEです。 |
| `width` | INT | いいえ | 16 - MAX_RESOLUTION | 出力動画の幅（ピクセル単位）です。16で割り切れる必要があります。（デフォルト: 832） |
| `height` | INT | いいえ | 16 - MAX_RESOLUTION | 出力動画の高さ（ピクセル単位）です。16で割り切れる必要があります。（デフォルト: 480） |
| `length` | INT | いいえ | 1 - MAX_RESOLUTION | 生成するフレーム数です。（デフォルト: 81） |
| `clip_vision_output` | CLIPVISIONOUTPUT | いいえ | - | 追加の条件付けのためのオプションのCLIP vision出力です。 |
| `start_image` | IMAGE | いいえ | - | 動画シーケンスを初期化するためのオプションの開始画像です。 |
| `audio_encoder_output_1` | AUDIOENCODEROUTPUT | はい | - | 1人目の話者の特徴量を含む、主要な音声エンコーダー出力です。 |
| `motion_frame_count` | INT | いいえ | 1 - 33 | シーケンスを拡張する際にモーションコンテキストとして使用する前フレームの数です。（デフォルト: 9） |
| `audio_scale` | FLOAT | いいえ | -10.0 - 10.0 | 音声条件付けに適用されるスケーリング係数です。（デフォルト: 1.0） |
| `previous_frames` | IMAGE | いいえ | - | 拡張元となるオプションの前の動画フレームです。 |
| `audio_encoder_output_2` | AUDIOENCODEROUTPUT | いいえ | - | 2人目の音声エンコーダー出力です。`mode`が`"two_speakers"`に設定されている場合に必須です。 |
| `mask_1` | MASK | いいえ | - | 1人目の話者のマスクです。2つの音声入力を使用する場合に必要です。 |
| `mask_2` | MASK | いいえ | - | 2人目の話者のマスクです。2つの音声入力を使用する場合に必要です。 |

**パラメータ制約:**

* `mode`が`"two_speakers"`に設定されている場合、パラメータ`audio_encoder_output_2`、`mask_1`、`mask_2`は必須になります。
* `audio_encoder_output_2`が提供される場合、`mask_1`と`mask_2`も両方提供する必要があります。
* `mask_1`と`mask_2`が提供される場合、`audio_encoder_output_2`も提供する必要があります。
* `previous_frames`が提供される場合、`motion_frame_count`で指定された数以上のフレームを含んでいる必要があります。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `model` | MODEL | 音声条件付けが適用されたパッチ済みモデルです。 |
| `positive` | CONDITIONING | 追加のコンテキスト（例：開始画像、CLIP vision）で修正された可能性のあるポジティブな条件付けです。 |
| `negative` | CONDITIONING | 追加のコンテキストで修正された可能性のあるネガティブな条件付けです。 |
| `latent` | LATENT | 潜在空間における生成された動画シーケンスです。 |
| `trim_image` | INT | シーケンスを拡張する際に、モーションコンテキストの先頭からトリミングすべきフレーム数です。 |
