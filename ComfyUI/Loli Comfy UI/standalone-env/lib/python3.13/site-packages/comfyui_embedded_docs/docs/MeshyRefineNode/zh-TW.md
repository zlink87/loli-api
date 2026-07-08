> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/zh-TW.md)

Meshy: Refine Draft Model 節點接收先前生成的 3D 草稿模型並提升其品質，可選擇性地添加紋理。它會向 Meshy API 提交一個精煉任務，並在處理完成後返回最終的 3D 模型檔案。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"latest"` | 指定用於精煉的 AI 模型。目前僅提供 "latest" 模型。 |
| `meshy_task_id` | MESHY_TASK_ID | 是 | - | 您想要精煉的草稿模型的唯一任務 ID。 |
| `enable_pbr` | BOOLEAN | 否 | - | 除了基礎顏色外，還生成 PBR 貼圖（金屬度、粗糙度、法線）。注意：使用雕塑風格時應設為 false，因為雕塑風格會生成自己的一套 PBR 貼圖。（預設值：`False`） |
| `texture_prompt` | STRING | 否 | - | 提供文字提示來引導紋理生成過程。最多 600 個字元。不能與 'texture_image' 同時使用。（預設值：空字串） |
| `texture_image` | IMAGE | 否 | - | 'texture_image' 和 'texture_prompt' 只能同時使用其中一個。（可選） |

**注意：** `texture_prompt` 和 `texture_image` 輸入是互斥的。您不能在同一操作中同時提供文字提示和圖像來進行紋理處理。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 生成的 GLB 模型檔案名稱。（僅供向後兼容使用） |
| `meshy_task_id` | MESHY_TASK_ID | 已提交的精煉任務的唯一任務 ID。 |
| `GLB` | FILE3DGLB | 最終精煉的 3D 模型，格式為 GLB。 |
| `FBX` | FILE3DFBX | 最終精煉的 3D 模型，格式為 FBX。 |
