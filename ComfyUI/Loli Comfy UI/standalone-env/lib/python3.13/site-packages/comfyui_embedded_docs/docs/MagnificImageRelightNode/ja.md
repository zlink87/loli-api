> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageRelightNode/ja.md)

Magnific Image Relightノードは、入力画像の照明を調整します。テキストプロンプトに基づいたスタイル的な照明を適用したり、オプションの参照画像から照明の特性を転写したりすることができます。このノードは、最終出力の明るさ、コントラスト、全体的な雰囲気を微調整するための様々なコントロールを提供します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | はい | N/A | 照明を調整する画像です。画像は1枚のみ必要です。最小サイズは160x160ピクセルです。アスペクト比は1:3から3:1の間である必要があります。 |
| `prompt` | STRING | いいえ | N/A | 照明に関する記述的なガイダンスです。強調表記（1-1.4）をサポートします。デフォルトは空の文字列です。 |
| `light_transfer_strength` | INT | はい | 0 から 100 | 光の転写を適用する強度です。デフォルト: 100。 |
| `style` | COMBO | はい | `"standard"`<br>`"darker_but_realistic"`<br>`"clean"`<br>`"smooth"`<br>`"brighter"`<br>`"contrasted_n_hdr"`<br>`"just_composition"` | スタイル的な出力の好みを設定します。 |
| `interpolate_from_original` | BOOLEAN | はい | N/A | 生成の自由度を制限し、オリジナルにより近く一致させます。デフォルト: False。 |
| `change_background` | BOOLEAN | はい | N/A | プロンプトまたは参照画像に基づいて背景を変更します。デフォルト: True。 |
| `preserve_details` | BOOLEAN | はい | N/A | オリジナルからのテクスチャや細部を維持します。デフォルト: True。 |
| `advanced_settings` | DYNAMICCOMBO | はい | `"disabled"`<br>`"enabled"` | 高度な照明制御のための微調整オプションです。`"enabled"`に設定すると、追加のパラメータが利用可能になります。 |
| `reference_image` | IMAGE | いいえ | N/A | 照明を転写するためのオプションの参照画像です。提供する場合は、画像は1枚のみ必要です。最小サイズは160x160ピクセルです。アスペクト比は1:3から3:1の間である必要があります。 |

**高度な設定に関する注意:** `advanced_settings`が`"enabled"`に設定されている場合、以下のネストされたパラメータが有効になります:

* `whites`: 画像内の最も明るいトーンを調整します。範囲: 0 から 100。デフォルト: 50。
* `blacks`: 画像内の最も暗いトーンを調整します。範囲: 0 から 100。デフォルト: 50。
* `brightness`: 全体的な明るさの調整です。範囲: 0 から 100。デフォルト: 50。
* `contrast`: コントラストの調整です。範囲: 0 から 100。デフォルト: 50。
* `saturation`: 色の彩度の調整です。範囲: 0 から 100。デフォルト: 50。
* `engine`: 処理エンジンの選択です。オプション: `"automatic"`, `"balanced"`, `"cool"`, `"real"`, `"illusio"`, `"fairy"`, `"colorful_anime"`, `"hard_transform"`, `"softy"`。
* `transfer_light_a`: 光の転写の強度です。オプション: `"automatic"`, `"low"`, `"medium"`, `"normal"`, `"high"`, `"high_on_faces"`。
* `transfer_light_b`: 光の転写強度も変更します。前のコントロールと組み合わせて様々な効果を得ることができます。オプション: `"automatic"`, `"composition"`, `"straight"`, `"smooth_in"`, `"smooth_out"`, `"smooth_both"`, `"reverse_both"`, `"soft_in"`, `"soft_out"`, `"soft_mid"`, `"style_shift"`, `"strong_shift"`。
* `fixed_generation`: 同じ設定で一貫した出力を保証します。デフォルト: True。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `image` | IMAGE | 照明が調整された画像です。 |
