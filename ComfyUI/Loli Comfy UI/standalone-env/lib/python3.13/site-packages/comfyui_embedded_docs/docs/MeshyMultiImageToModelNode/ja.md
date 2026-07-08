> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyMultiImageToModelNode/ja.md)

このノードは、Meshy APIを使用して複数の入力画像から3Dモデルを生成します。提供された画像をアップロードし、処理タスクを送信して、結果の3Dモデルファイル（GLBおよびFBX）と参照用のタスクIDを返します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
| :--- | :--- | :--- | :--- | :--- |
| `model` | COMBO | はい | `"latest"` | 使用するAIモデルのバージョンを指定します。 |
| `images` | IMAGE | はい | 2 から 4 枚の画像 | 3Dモデルを生成するために使用する一連の画像です。2枚から4枚の画像を提供する必要があります。 |
| `should_remesh` | COMBO | はい | `"true"`<br>`"false"` | 生成されたメッシュを処理するかどうかを決定します。`"false"`に設定すると、ノードは未処理の三角メッシュを返します。 |
| `topology` | COMBO | いいえ | `"triangle"`<br>`"quad"` | リメッシュされた出力の目標ポリゴンタイプです。このパラメータは、`should_remesh`が`"true"`に設定されている場合にのみ利用可能で必須となります。 |
| `target_polycount` | INT | いいえ | 100 から 300000 | リメッシュされたモデルの目標ポリゴン数です（デフォルト: 300000）。このパラメータは、`should_remesh`が`"true"`に設定されている場合にのみ利用可能です。 |
| `symmetry_mode` | COMBO | はい | `"auto"`<br>`"on"`<br>`"off"` | 生成されるモデルに対称性を適用するかどうかを制御します。 |
| `should_texture` | COMBO | はい | `"true"`<br>`"false"` | テクスチャを生成するかどうかを決定します。`"false"`に設定すると、テクスチャフェーズをスキップし、テクスチャのないメッシュを返します。 |
| `enable_pbr` | BOOLEAN | いいえ | `True` / `False` | `should_texture`が`"true"`の場合、このオプションはベースカラーに加えてPBRマップ（メタリック、ラフネス、法線）を生成します（デフォルト: `False`）。 |
| `texture_prompt` | STRING | いいえ | - | テクスチャリングプロセスをガイドするためのテキストプロンプトです（最大600文字）。`texture_image`と同時に使用することはできません。このパラメータは、`should_texture`が`"true"`に設定されている場合にのみ利用可能です。 |
| `texture_image` | IMAGE | いいえ | - | テクスチャリングプロセスをガイドするための画像です。`texture_image`と`texture_prompt`のいずれか一方のみを同時に使用できます。このパラメータは、`should_texture`が`"true"`に設定されている場合にのみ利用可能です。 |
| `pose_mode` | COMBO | はい | `""`<br>`"A-pose"`<br>`"T-pose"` | 生成されるモデルのポーズモードを指定します。 |
| `seed` | INT | はい | 0 から 2147483647 | 生成プロセスのためのシード値です（デフォルト: 0）。結果はシードに関わらず非決定的ですが、シードを変更することでノードの再実行をトリガーできます。 |

**パラメータの制約:**

* `images`入力には、2枚から4枚の画像を提供する必要があります。
* `topology`および`target_polycount`パラメータは、`should_remesh`が`"true"`に設定されている場合にのみ有効になります。
* `enable_pbr`、`texture_prompt`、`texture_image`パラメータは、`should_texture`が`"true"`に設定されている場合にのみ有効になります。
* `texture_prompt`と`texture_image`は同時に使用できません。これらは相互排他的です。

## 出力

| 出力名 | データ型 | 説明 |
| :--- | :--- | :--- |
| `model_file` | STRING | 生成されたGLBモデルのファイル名です。この出力は後方互換性のために提供されています。 |
| `meshy_task_id` | MESHY_TASK_ID | Meshy APIタスクの一意の識別子です。 |
| `GLB` | FILE3DGLB | GLB形式で生成された3Dモデルです。 |
| `FBX` | FILE3DFBX | FBX形式で生成された3Dモデルです。 |
