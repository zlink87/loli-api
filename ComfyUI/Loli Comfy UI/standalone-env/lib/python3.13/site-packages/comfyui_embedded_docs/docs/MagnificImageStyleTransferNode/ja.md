> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageStyleTransferNode/ja.md)

このノードは、参照画像から視覚的なスタイルを入力画像に適用します。外部のAIサービスを使用して画像を処理し、スタイル転写の強度や元画像の構造の保持を制御できます。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | はい | - | スタイル転写を適用する画像です。 |
| `reference_image` | IMAGE | はい | - | スタイルを抽出する参照画像です。 |
| `prompt` | STRING | いいえ | - | スタイル転写をガイドするためのオプションのテキストプロンプトです。 |
| `style_strength` | INT | いいえ | 0 から 100 | スタイルの強度の割合です（デフォルト: 100）。 |
| `structure_strength` | INT | いいえ | 0 から 100 | 元画像の構造を維持します（デフォルト: 50）。 |
| `flavor` | COMBO | いいえ | "faithful"<br>"gen_z"<br>"psychedelia"<br>"detaily"<br>"clear"<br>"donotstyle"<br>"donotstyle_sharp" | スタイル転写のフレーバーです。 |
| `engine` | COMBO | いいえ | "balanced"<br>"definio"<br>"illusio"<br>"3d_cartoon"<br>"colorful_anime"<br>"caricature"<br>"real"<br>"super_real"<br>"softy" | 処理エンジンの選択です。 |
| `portrait_mode` | COMBO | いいえ | "disabled"<br>"enabled" | 顔の強調のためのポートレートモードを有効にします。 |
| `portrait_style` | COMBO | いいえ | "standard"<br>"pop"<br>"super_pop" | ポートレート画像に適用される視覚スタイルです。この入力は`portrait_mode`が"enabled"に設定されている場合のみ利用可能です。 |
| `portrait_beautifier` | COMBO | いいえ | "none"<br>"beautify_face"<br>"beautify_face_max" | ポートレートに対する顔の美化の強度です。この入力は`portrait_mode`が"enabled"に設定されている場合のみ利用可能です。 |
| `fixed_generation` | BOOLEAN | いいえ | - | 無効にすると、各生成にランダム性が導入され、より多様な結果が得られます（デフォルト: True）。 |

**制約事項:**

* `image`と`reference_image`はそれぞれ1つずつ必要です。
* 両方の画像のアスペクト比は1:3から3:1の間である必要があります。
* 両方の画像の高さと幅は最低160ピクセルである必要があります。
* `portrait_style`および`portrait_beautifier`パラメータは、`portrait_mode`が"enabled"に設定されている場合にのみ有効かつ必須となります。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `image` | IMAGE | スタイル転写が適用された結果の画像です。 |
