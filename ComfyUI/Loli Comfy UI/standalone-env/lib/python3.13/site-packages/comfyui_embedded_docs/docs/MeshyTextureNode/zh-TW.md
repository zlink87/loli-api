> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextureNode/zh-TW.md)

此節點將 AI 產生的紋理套用到 3D 模型上。它接收來自先前 Meshy 3D 生成或轉換節點的任務 ID，並使用文字描述或參考圖像來為模型建立新的紋理。該節點會輸出 GLB 和 FBX 檔案格式的帶紋理模型。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"latest"` | 用於紋理生成的 AI 模型版本。目前僅提供 "latest" 版本。 |
| `meshy_task_id` | MESHY_TASK_ID | 是 | - | 來自先前 Meshy 3D 生成或轉換任務的唯一識別碼（任務 ID）。這提供了要進行紋理處理的基礎 3D 模型。 |
| `enable_original_uv` | BOOLEAN | 否 | - | 啟用時（預設：`True`），節點將使用上傳模型的原始 UV 布局，保留任何現有紋理。如果模型沒有原始 UV，輸出品質可能會較低。 |
| `pbr` | BOOLEAN | 否 | - | 為帶紋理的模型啟用基於物理的渲染（PBR）材質輸出（預設：`False`）。 |
| `text_style_prompt` | STRING | 否 | - | 物件所需紋理風格的文字描述。最多 600 個字元。不能與 `image_style` 同時使用。 |
| `image_style` | IMAGE | 否 | - | 用於引導紋理處理過程的 2D 參考圖像。不能與 `text_style_prompt` 同時使用。 |

**參數限制：**

* 您必須提供 `text_style_prompt` 或 `image_style` 其中一項，但不能同時提供兩者。
* `text_style_prompt` 最多限制為 600 個字元。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成的 GLB 模型的檔案名稱。此輸出是為了向後兼容而提供。 |
| `meshy_task_id` | MODEL_TASK_ID | 此紋理處理工作的唯一任務識別碼，可用於引用結果。 |
| `GLB` | FILE3DGLB | 以 GLB 檔案格式儲存的帶紋理 3D 模型。 |
| `FBX` | FILE3DFBX | 以 FBX 檔案格式儲存的帶紋理 3D 模型。 |
