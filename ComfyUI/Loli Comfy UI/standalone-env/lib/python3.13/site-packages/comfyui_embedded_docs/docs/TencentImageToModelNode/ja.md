> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/ja.md)

このノードは、TencentのHunyuan3D Pro APIを使用して、1つ以上の入力画像から3Dモデルを生成します。画像を処理し、APIに送信し、生成された3DモデルファイルをGLBおよびOBJ形式で返します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | はい | `"3.0"`<br>`"3.1"` | 使用するHunyuan3Dモデルのバージョンです。`3.1`モデルではLowPolyオプションは利用できません。 |
| `image` | IMAGE | はい | - | 3Dモデル生成に使用する主要な入力画像です。 |
| `image_left` | IMAGE | いいえ | - | マルチビュー生成のための、オブジェクトの左側面のオプション画像です。 |
| `image_right` | IMAGE | いいえ | - | マルチビュー生成のための、オブジェクトの右側面のオプション画像です。 |
| `image_back` | IMAGE | いいえ | - | マルチビュー生成のための、オブジェクトの背面のオプション画像です。 |
| `face_count` | INT | はい | 40000 - 1500000 | 生成される3Dモデルの目標面数です（デフォルト: 500000）。 |
| `generate_type` | DYNAMICCOMBO | はい | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | 生成する3Dモデルのタイプです。オプションを選択すると、関連する追加パラメータが表示されます。 |
| `generate_type.pbr` | BOOLEAN | いいえ | - | 物理ベースレンダリング（PBR）マテリアルの生成を有効にします。このパラメータは、`generate_type`が"Normal"または"LowPoly"に設定されている場合にのみ表示されます（デフォルト: False）。 |
| `generate_type.polygon_type` | COMBO | いいえ | `"triangle"`<br>`"quadrilateral"` | メッシュに使用するポリゴンのタイプです。このパラメータは、`generate_type`が"LowPoly"に設定されている場合にのみ表示されます。 |
| `seed` | INT | はい | 0 - 2147483647 | 生成プロセス用のシード値です。シードはノードを再実行するかどうかを制御しますが、結果はシードに関係なく非決定的です（デフォルト: 0）。 |

**注意:** すべての入力画像は、幅と高さが最低128ピクセル以上である必要があります。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `model_file` | STRING | 後方互換性のためのレガシー出力です。 |
| `GLB` | FILE3DGLB | GLB（Binary GL Transmission Format）ファイル形式で生成された3Dモデルです。 |
| `OBJ` | FILE3DOBJ | OBJ（Wavefront）ファイル形式で生成された3Dモデルです。 |
