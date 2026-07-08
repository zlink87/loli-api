> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerPreciseV2Node/zh-TW.md)

Magnific Image Upscale (Precise V2) 節點執行高保真度的影像放大，並能精確控制銳利度、顆粒感和細節增強。它透過外部 API 處理影像，支援最高 10060×10060 像素的輸出解析度。此節點提供不同的處理風格，並且在要求的輸出尺寸超過允許的最大值時，可以自動縮小輸入影像。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | 是 | - | 要進行放大的輸入影像。必須且僅能提供一張影像。最小尺寸為 160x160 像素。長寬比必須介於 1:3 到 3:1 之間。 |
| `scale_factor` | STRING | 是 | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | 期望的放大倍率。 |
| `flavor` | STRING | 是 | `"sublime"`<br>`"photo"`<br>`"photo_denoiser"` | 處理風格。"sublime" 適用於一般用途，"photo" 針對照片進行優化，"photo_denoiser" 則適用於有雜訊的照片。 |
| `sharpen` | INT | 否 | 0 至 100 | 控制影像銳利化的強度，以增強邊緣定義和清晰度。數值越高，結果越銳利。預設值：7。 |
| `smart_grain` | INT | 否 | 0 至 100 | 添加智慧型顆粒或紋理增強，以防止放大後的影像看起來過於平滑或人工化。預設值：7。 |
| `ultra_detail` | INT | 否 | 0 至 100 | 控制在放大過程中添加的精細細節、紋理和微觀細節的數量。預設值：30。 |
| `auto_downscale` | BOOLEAN | 否 | - | 啟用後，如果計算出的輸出尺寸超過允許的最大解析度 10060x10060 像素，節點將自動縮小輸入影像。這有助於防止錯誤，但可能會影響品質。預設值：False。 |

**注意：** 如果 `auto_downscale` 被禁用，且要求的輸出尺寸（輸入尺寸 × `scale_factor`）超過 10060x10060 像素，節點將會引發錯誤。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 放大後產生的影像。 |
