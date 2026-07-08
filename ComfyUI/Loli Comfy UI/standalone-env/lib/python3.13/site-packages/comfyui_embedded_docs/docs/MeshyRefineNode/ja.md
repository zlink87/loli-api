> このドキュメントは AI によって生成されました。エラーを見つけた場合や改善のご提案がある場合は、ぜひ貢献してください！ [GitHub で編集](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/ja.md)

Meshy: Refine Draft Model ノードは、以前に生成された3Dドラフトモデルを受け取り、品質を向上させ、オプションでテクスチャを追加します。Meshy APIにリファインメントタスクを送信し、処理が完了すると最終的な3Dモデルファイルを返します。

## 入力

| パラメータ | データ型 | 必須 | 範囲 | 説明 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | はい | `"latest"` | リファインメントに使用するAIモデルを指定します。現在は"latest"モデルのみ利用可能です。 |
| `meshy_task_id` | MESHY_TASK_ID | はい | - | リファインしたいドラフトモデルの一意のタスクIDです。 |
| `enable_pbr` | BOOLEAN | いいえ | - | ベースカラーに加えて、PBRマップ（メタリック、ラフネス、ノーマル）を生成します。注意：Sculptureスタイルを使用する場合は、Sculptureスタイルが独自のPBRマップセットを生成するため、falseに設定する必要があります。（デフォルト: `False`） |
| `texture_prompt` | STRING | いいえ | - | テクスチャリングプロセスをガイドするためのテキストプロンプトを提供します。最大600文字。'texture_image'と同時に使用することはできません。（デフォルト: 空文字列） |
| `texture_image` | IMAGE | いいえ | - | 'texture_image' または 'texture_prompt' のいずれか一方のみを同時に使用できます。（オプション） |

**注意:** `texture_prompt` と `texture_image` の入力は相互排他的です。テクスチャリングのためにテキストプロンプトと画像の両方を同じ操作で提供することはできません。

## 出力

| 出力名 | データ型 | 説明 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成されたGLBモデルのファイル名です。（後方互換性のためのみ） |
| `meshy_task_id` | MESHY_TASK_ID | 送信されたリファインメントジョブの一意のタスクIDです。 |
| `GLB` | FILE3DGLB | GLB形式の最終的なリファイン済み3Dモデルです。 |
| `FBX` | FILE3DFBX | FBX形式の最終的なリファイン済み3Dモデルです。 |
