> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedImageUpscaleNode/zh-TW.md)

WaveSpeed 影像放大節點使用外部 AI 服務來提升影像的解析度和品質。它接收單張輸入照片，並將其放大至更高的目標解析度，例如 2K、4K 或 8K，從而產生更清晰、細節更豐富的結果。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | 是 | `"SeedVR2"`<br>`"Ultimate"` | 用於影像放大的 AI 模型。"SeedVR2" 和 "Ultimate" 提供不同等級的品質和價格方案。 |
| `image` | IMAGE | 是 | | 待放大的輸入影像。 |
| `target_resolution` | STRING | 是 | `"2K"`<br>`"4K"`<br>`"8K"` | 放大後影像期望的輸出解析度。 |

**注意：** 此節點需要且僅能接受一張輸入影像。提供批次影像將會導致錯誤。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 經過放大處理的高解析度輸出影像。 |
