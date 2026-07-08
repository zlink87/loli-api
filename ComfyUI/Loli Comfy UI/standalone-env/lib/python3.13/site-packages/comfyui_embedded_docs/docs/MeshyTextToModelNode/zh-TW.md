> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextToModelNode/zh-TW.md)

此節點使用 Meshy API，根據文字描述生成 3D 模型。它會將您的提示詞和設定發送至 API，等待生成完成後下載產生的模型檔案。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"latest"` | 指定要使用的 AI 模型版本。目前僅提供 "latest" 版本。 |
| `prompt` | STRING | 是 | - | 您想要生成的 3D 模型文字描述。長度必須在 1 到 600 個字元之間。 |
| `style` | COMBO | 是 | `"realistic"`<br>`"sculpture"` | 生成 3D 模型的藝術風格。 |
| `should_remesh` | DYNAMIC COMBO | 是 | `"true"`<br>`"false"` | 控制是否處理生成的網格。設定為 "false" 時，節點將返回未經處理的三角網格。選擇 "true" 會顯示拓撲和多邊形數量的額外參數。 |
| `topology` | COMBO | 否* | `"triangle"`<br>`"quad"` | 重新網格化模型的目標多邊形類型。此參數僅在 `should_remesh` 設定為 "true" 時可用且為必需。 |
| `target_polycount` | INT | 否* | 100 - 300000 | 重新網格化模型的目標多邊形數量。預設為 300000。此參數僅在 `should_remesh` 設定為 "true" 時可用且為必需。 |
| `symmetry_mode` | COMBO | 是 | `"auto"`<br>`"on"`<br>`"off"` | 控制生成模型中的對稱性。 |
| `pose_mode` | COMBO | 是 | `""`<br>`"A-pose"`<br>`"T-pose"` | 指定生成模型的姿勢模式。空字串表示不請求特定姿勢。 |
| `seed` | INT | 是 | 0 - 2147483647 | 用於生成的種子值。設定此值可控制節點是否應重新執行，但無論種子值為何，結果都是非確定性的。預設為 0。 |

*注意：`topology` 和 `target_polycount` 參數為條件性必需。它們僅在 `should_remesh` 參數設定為 "true" 時出現且必須設定。

## 輸出

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成的 GLB 模型檔案名稱。此輸出是為了向後兼容而提供。 |
| `meshy_task_id` | MESHY_TASK_ID | Meshy API 任務的唯一識別碼。 |
| `GLB` | FILE3DGLB | 以 GLB 格式生成的 3D 模型檔案。 |
| `FBX` | FILE3DFBX | 以 FBX 格式生成的 3D 模型檔案。 |
