> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyAnimateModelNode/zh-TW.md)

此節點對已使用 Meshy 服務綁定骨架的 3D 角色模型套用特定動畫。它接收先前綁定操作產生的任務 ID 以及一個動作 ID，用於從動畫庫中選擇所需的動畫。節點隨後處理請求，並以 GLB 和 FBX 兩種檔案格式返回帶有動畫的模型。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 數值範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `rig_task_id` | STRING | 是 | N/A | 來自先前已完成的 Meshy 角色綁定操作之唯一任務 ID。 |
| `action_id` | INT | 是 | 0 至 696 | 要套用的動畫動作之 ID 編號。請造訪 <https://docs.meshy.ai/en/api/animation-library> 以查看可用數值列表。(預設值: 0) |

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 動畫模型的字串識別碼。此輸出僅為向後相容性而提供。 |
| `GLB` | FILE3DGLB | GLB 格式的動畫 3D 模型檔案。 |
| `FBX` | FILE3DFBX | FBX 格式的動畫 3D 模型檔案。 |
