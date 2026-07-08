> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyImageToModelNode/ja.md)

Meshy: Image to Model ノードは、Meshy API を使用して単一の入力画像から3Dモデルを生成します。画像をアップロードし、処理タスクを送信して、生成された3Dモデルファイル（GLBおよびFBX）と参照用のタスクIDを返します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | はい | `"latest"` | 生成に使用するAIモデルのバージョンを指定します。 |
| `image` | IMAGE | はい | - | 3Dモデルに変換する入力画像です。 |
| `should_remesh` | DYNAMIC COMBO | はい | `"true"`<br>`"false"` | 生成されたメッシュを処理するかどうかを決定します。`"false"`に設定すると、処理されていない三角メッシュが返されます。 |
| `topology` | COMBO | 条件付き* | `"triangle"`<br>`"quad"` | リメッシュされたモデルの目標ポリゴントポロジーです。この入力は、`should_remesh`が`"true"`に設定されている場合にのみ利用可能で必須となります。 |
| `target_polycount` | INT | 条件付き* | 100 - 300000 | リメッシュされたモデルの目標ポリゴン数です。この入力は、`should_remesh`が`"true"`に設定されている場合にのみ利用可能で必須となります。デフォルト値は300000です。 |
| `symmetry_mode` | COMBO | はい | `"auto"`<br>`"on"`<br>`"off"` | 生成される3Dモデルに適用される対称性を制御します。 |
| `should_texture` | DYNAMIC COMBO | はい | `"true"`<br>`"false"` | モデルにテクスチャを生成するかどうかを決定します。`"false"`に設定すると、テクスチャフェーズをスキップし、テクスチャなしのメッシュを返します。 |
| `enable_pbr` | BOOLEAN | 条件付き* | - | `should_texture`が`"true"`の場合、このオプションはベースカラーに加えてPBRマップ（メタリック、ラフネス、法線）を生成します。デフォルト値は`False`です。 |
| `texture_prompt` | STRING | 条件付き* | - | テクスチャリングプロセスをガイドするテキストプロンプトです（最大600文字）。この入力は、`should_texture`が`"true"`の場合にのみ利用可能です。`texture_image`と同時に使用することはできません。 |
| `texture_image` | IMAGE | 条件付き* | - | テクスチャリングプロセスをガイドする画像です。この入力は、`should_texture`が`"true"`の場合にのみ利用可能です。`texture_prompt`と同時に使用することはできません。 |
| `pose_mode` | COMBO | はい | `""`<br>`"A-pose"`<br>`"T-pose"` | 生成されるモデルのポーズモードを指定します。 |
| `seed` | INT | はい | 0 - 2147483647 | 生成プロセス用のシード値です。シード値に関わらず、結果は非決定的です。デフォルト値は0です。 |

**パラメータ制約に関する注意:**

* `topology`および`target_polycount`入力は、`should_remesh`が`"true"`に設定されている場合にのみ必須です。
* `enable_pbr`、`texture_prompt`、`texture_image`入力は、`should_texture`が`"true"`に設定されている場合にのみ利用可能です。
* `texture_prompt`と`texture_image`を同時に使用することはできません。`should_texture`が`"true"`の場合に両方が提供されると、ノードはエラーを発生させます。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成されたGLBモデルのファイル名です。（後方互換性のために維持されています）。 |
| `meshy_task_id` | MESHY_TASK_ID | Meshy APIタスクの一意の識別子で、参照やトラブルシューティングに使用できます。 |
| `GLB` | FILE3DGLB | GLBファイル形式で生成された3Dモデルです。 |
| `FBX` | FILE3DFBX | FBXファイル形式で生成された3Dモデルです。 |
