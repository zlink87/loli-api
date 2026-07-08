> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyMultiImageToModelNode/zh-TW.md)

此節點使用 Meshy API 從多張輸入圖像生成 3D 模型。它會上傳提供的圖像，提交處理任務，並返回生成的 3D 模型檔案（GLB 和 FBX）以及用於參考的任務 ID。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
| :--- | :--- | :--- | :--- | :--- |
| `model` | COMBO | 是 | `"latest"` | 指定要使用的 AI 模型版本。 |
| `images` | IMAGE | 是 | 2 到 4 張圖像 | 用於生成 3D 模型的一組圖像。您必須提供 2 到 4 張圖像。 |
| `should_remesh` | COMBO | 是 | `"true"`<br>`"false"` | 決定生成的網格是否應進行處理。設為 `"false"` 時，節點將返回未處理的三角網格。 |
| `topology` | COMBO | 否 | `"triangle"`<br>`"quad"` | 重新網格化輸出的目標多邊形類型。此參數僅在 `should_remesh` 設為 `"true"` 時可用且為必需。 |
| `target_polycount` | INT | 否 | 100 到 300000 | 重新網格化模型的目標多邊形數量（預設值：300000）。此參數僅在 `should_remesh` 設為 `"true"` 時可用。 |
| `symmetry_mode` | COMBO | 是 | `"auto"`<br>`"on"`<br>`"off"` | 控制是否對生成的模型應用對稱性。 |
| `should_texture` | COMBO | 是 | `"true"`<br>`"false"` | 決定是否生成紋理。設為 `"false"` 將跳過紋理階段，並返回沒有紋理的網格。 |
| `enable_pbr` | BOOLEAN | 否 | `True` / `False` | 當 `should_texture` 為 `"true"` 時，此選項會生成 PBR 貼圖（金屬度、粗糙度、法線）以及基礎顏色（預設值：`False`）。 |
| `texture_prompt` | STRING | 否 | - | 用於指導紋理生成過程的文字提示（最多 600 個字元）。不能與 `texture_image` 同時使用。此參數僅在 `should_texture` 設為 `"true"` 時可用。 |
| `texture_image` | IMAGE | 否 | - | 用於指導紋理生成過程的圖像。`texture_image` 和 `texture_prompt` 只能同時使用其中一個。此參數僅在 `should_texture` 設為 `"true"` 時可用。 |
| `pose_mode` | COMBO | 是 | `""`<br>`"A-pose"`<br>`"T-pose"` | 指定生成模型的姿勢模式。 |
| `seed` | INT | 是 | 0 到 2147483647 | 生成過程的種子值（預設值：0）。無論種子為何，結果都是非確定性的，但更改種子可以觸發節點重新執行。 |

**參數限制：**

* 您必須為 `images` 輸入提供 2 到 4 張圖像。
* `topology` 和 `target_polycount` 參數僅在 `should_remesh` 設為 `"true"` 時有效。
* `enable_pbr`、`texture_prompt` 和 `texture_image` 參數僅在 `should_texture` 設為 `"true"` 時有效。
* 您不能同時使用 `texture_prompt` 和 `texture_image`；它們是互斥的。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
| :--- | :--- | :--- |
| `model_file` | STRING | 生成的 GLB 模型的檔案名稱。此輸出是為了向後兼容而提供。 |
| `meshy_task_id` | MESHY_TASK_ID | Meshy API 任務的唯一識別碼。 |
| `GLB` | FILE3DGLB | 以 GLB 格式生成的 3D 模型。 |
| `FBX` | FILE3DFBX | 以 FBX 格式生成的 3D 模型。 |
