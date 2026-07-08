> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRigModelNode/zh-TW.md)

Meshy: Rig Model 節點接收來自 Meshy 的 3D 模型任務，並生成一個已綁定骨架的角色模型。它會自動為模型創建骨架，使其能夠被擺姿勢和動畫化。該節點會以 GLB 和 FBX 兩種檔案格式輸出已綁定骨架的模型。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `meshy_task_id` | STRING | 是 | N/A | 來自先前 Meshy 操作（例如文字轉 3D 或圖片轉 3D）的唯一任務 ID，該操作生成了需要綁定骨架的模型。 |
| `height_meters` | FLOAT | 是 | 0.1 至 15.0 | 角色模型的近似高度（單位：公尺）。這有助於提高縮放和綁定骨架的準確性（預設值：1.7）。 |
| `texture_image` | IMAGE | 否 | N/A | 模型的 UV 展開基礎顏色紋理圖片。 |

**注意：** 目前的自動綁定骨架流程不適用於未貼圖的網格、非人形資產，或肢體與身體結構不明確的人形資產。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 用於向後相容的舊版輸出，包含 GLB 模型的檔案名稱。 |
| `rig_task_id` | STRING | 此綁定骨架操作的唯一任務 ID，可用於引用結果。 |
| `GLB` | FILE3DGLB | 以 GLB 檔案格式儲存的已綁定骨架 3D 角色模型。 |
| `FBX` | FILE3DFBX | 以 FBX 檔案格式儲存的已綁定骨架 3D 角色模型。 |
