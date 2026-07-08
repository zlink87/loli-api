> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyImageToModelNode/zh-TW.md)

Meshy: Image to Model 節點使用 Meshy API 從單一輸入圖像生成 3D 模型。它會上傳您的圖像，提交處理任務，並返回生成的 3D 模型檔案（GLB 和 FBX）以及用於參考的任務 ID。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"latest"` | 指定用於生成的 AI 模型版本。 |
| `image` | IMAGE | 是 | - | 要轉換為 3D 模型的輸入圖像。 |
| `should_remesh` | DYNAMIC COMBO | 是 | `"true"`<br>`"false"` | 決定生成的網格是否應進行處理。當設定為 `"false"` 時，節點將返回未經處理的三角網格。 |
| `topology` | COMBO | 否* | `"triangle"`<br>`"quad"` | 重新網格化模型的目標多邊形拓撲。此輸入僅在 `should_remesh` 設定為 `"true"` 時可用且為必需。 |
| `target_polycount` | INT | 否* | 100 - 300000 | 重新網格化模型的目標多邊形數量。此輸入僅在 `should_remesh` 設定為 `"true"` 時可用且為必需。預設值為 300000。 |
| `symmetry_mode` | COMBO | 是 | `"auto"`<br>`"on"`<br>`"off"` | 控制應用於生成 3D 模型的對稱性。 |
| `should_texture` | DYNAMIC COMBO | 是 | `"true"`<br>`"false"` | 決定是否為模型生成紋理。將其設定為 `"false"` 將跳過紋理階段並返回沒有紋理的網格。 |
| `enable_pbr` | BOOLEAN | 否* | - | 當 `should_texture` 為 `"true"` 時，此選項會生成 PBR 貼圖（金屬度、粗糙度、法線）以及基礎顏色。預設值為 `False`。 |
| `texture_prompt` | STRING | 否* | - | 用於指導紋理處理過程的文字提示（最多 600 個字元）。此輸入僅在 `should_texture` 設定為 `"true"` 時可用。它不能與 `texture_image` 同時使用。 |
| `texture_image` | IMAGE | 否* | - | 用於指導紋理處理過程的圖像。此輸入僅在 `should_texture` 設定為 `"true"` 時可用。它不能與 `texture_prompt` 同時使用。 |
| `pose_mode` | COMBO | 是 | `""`<br>`"A-pose"`<br>`"T-pose"` | 指定生成模型的姿勢模式。 |
| `seed` | INT | 是 | 0 - 2147483647 | 生成過程的種子值。無論種子值為何，結果都是非確定性的。預設值為 0。 |

**參數限制說明：**

* `topology` 和 `target_polycount` 輸入僅在 `should_remesh` 設定為 `"true"` 時為必需。
* `enable_pbr`、`texture_prompt` 和 `texture_image` 輸入僅在 `should_texture` 設定為 `"true"` 時可用。
* 您不能同時使用 `texture_prompt` 和 `texture_image`。如果在 `should_texture` 為 `"true"` 時同時提供了兩者，節點將引發錯誤。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成的 GLB 模型的檔案名稱。（為保持向後兼容性而保留）。 |
| `meshy_task_id` | MESHY_TASK_ID | Meshy API 任務的唯一識別碼，可用於參考或故障排除。 |
| `GLB` | FILE3DGLB | 以 GLB 檔案格式生成的 3D 模型。 |
| `FBX` | FILE3DFBX | 以 FBX 檔案格式生成的 3D 模型。 |
