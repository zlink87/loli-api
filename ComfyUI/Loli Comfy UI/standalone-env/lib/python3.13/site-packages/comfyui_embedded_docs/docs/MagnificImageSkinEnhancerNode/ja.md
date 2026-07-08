> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageSkinEnhancerNode/ja.md)

Magnific Image Skin Enhancerノードは、ポートレート画像に特殊なAI処理を適用して肌の見た目を改善します。3つの異なるモードを提供し、それぞれ異なる目的に対応しています：クリエイティブ（芸術的な効果）、フェイスフル（元の見た目を保持）、フレキシブル（照明やリアリズムなど特定の改善を目的とした最適化）です。このノードは画像を外部APIにアップロードして処理を行い、強化された結果を返します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | はい | - | 強化するポートレート画像。 |
| `sharpen` | INT | いいえ | 0 から 100 | シャープネスの強度レベル（デフォルト: 0）。 |
| `smart_grain` | INT | いいえ | 0 から 100 | スマートグレインの強度レベル（デフォルト: 2）。 |
| `mode` | COMBO | はい | `"creative"`<br>`"faithful"`<br>`"flexible"` | 使用する処理モード。`"creative"`は芸術的な強化、`"faithful"`は元の見た目を保持、`"flexible"`は特定の目的に合わせた最適化を行います。 |
| `skin_detail` | INT | いいえ | 0 から 100 | 肌のディテール強化レベル。この入力は、`mode`が`"faithful"`に設定されている場合にのみ利用可能かつ必須となります（デフォルト: 80）。 |
| `optimized_for` | COMBO | いいえ | `"enhance_skin"`<br>`"improve_lighting"`<br>`"enhance_everything"`<br>`"transform_to_real"`<br>`"no_make_up"` | 強化の最適化対象。この入力は、`mode`が`"flexible"`に設定されている場合にのみ利用可能かつ必須となります。 |

**制約:**

* このノードは正確に1枚の入力画像を受け付けます。
* 入力画像の高さと幅は最低160ピクセル以上である必要があります。
* `skin_detail`パラメータは、`mode`が`"faithful"`に設定されている場合にのみ有効です。
* `optimized_for`パラメータは、`mode`が`"flexible"`に設定されている場合にのみ有効です。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `image` | IMAGE | 強化されたポートレート画像。 |
