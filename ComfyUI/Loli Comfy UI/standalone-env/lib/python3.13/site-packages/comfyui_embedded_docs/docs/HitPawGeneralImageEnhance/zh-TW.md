> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/zh-TW.md)

此節點透過將低解析度影像升頻至超解析度來增強影像品質，同時移除偽影和雜訊。它使用外部 API 處理影像，並能自動調整輸入尺寸以符合處理限制。允許的最大輸出尺寸為 400 萬畫素。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | 是 | `"generative_portrait"`<br>`"generative"` | 要使用的增強模型。 |
| `image` | IMAGE | 是 | - | 要增強的輸入影像。 |
| `upscale_factor` | INT | 是 | `1`<br>`2`<br>`4` | 影像尺寸的升頻倍數。 |
| `auto_downscale` | BOOLEAN | 否 | - | 如果輸出將超過限制，則自動縮小輸入影像。(預設值：`False`) |

**注意：** 如果計算出的輸出尺寸（輸入高度 × upscale_factor × 輸入寬度 × upscale_factor）超過 4,000,000 畫素（4MP）且 `auto_downscale` 被禁用，節點將引發錯誤。當啟用 `auto_downscale` 時，節點將嘗試先縮小輸入影像以符合限制，然後再套用請求的升頻倍數。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 增強並升頻後的輸出影像。 |
