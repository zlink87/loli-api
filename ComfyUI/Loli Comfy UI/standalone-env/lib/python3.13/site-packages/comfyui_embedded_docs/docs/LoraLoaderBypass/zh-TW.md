> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypass/zh-TW.md)

LoraLoaderBypass 節點以特殊的「旁路」模式將 LoRA（低秩適應）應用於擴散模型和 CLIP 模型。與標準的 LoRA 加載器不同，此方法不會永久修改基礎模型的權重。相反，它透過將 LoRA 的效果添加到模型的正常前向傳播中來計算輸出，這在訓練或處理權重已卸載的模型時非常有用。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | 是 | - | 要應用 LoRA 的擴散模型。 |
| `clip` | CLIP | 是 | - | 要應用 LoRA 的 CLIP 模型。 |
| `lora_name` | COMBO | 是 | *可用的 LoRA 檔案清單* | 要應用的 LoRA 檔案名稱。選項從 `loras` 資料夾載入。 |
| `strength_model` | FLOAT | 是 | -100.0 到 100.0 | 修改擴散模型的強度。此值可以為負數（預設值：1.0）。 |
| `strength_clip` | FLOAT | 是 | -100.0 到 100.0 | 修改 CLIP 模型的強度。此值可以為負數（預設值：1.0）。 |

**注意：** 如果 `strength_model` 和 `strength_clip` 均設為 0，節點將返回未經處理的原始 `model` 和 `clip` 輸入。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `MODEL` | MODEL | 以旁路模式應用了 LoRA 的擴散模型。 |
| `CLIP` | CLIP | 以旁路模式應用了 LoRA 的 CLIP 模型。 |
