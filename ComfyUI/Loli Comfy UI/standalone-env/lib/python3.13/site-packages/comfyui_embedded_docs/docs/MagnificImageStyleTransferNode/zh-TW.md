> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageStyleTransferNode/zh-TW.md)

此節點將參考圖像的視覺風格應用至您的輸入圖像。它使用外部 AI 服務來處理圖像，讓您可以控制風格轉換的強度以及原始圖像結構的保留程度。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | 是 | - | 要進行風格轉換的圖像。 |
| `reference_image` | IMAGE | 是 | - | 用於提取風格的參考圖像。 |
| `prompt` | STRING | 否 | - | 引導風格轉換的選用文字提示。 |
| `style_strength` | INT | 否 | 0 至 100 | 風格強度百分比（預設值：100）。 |
| `structure_strength` | INT | 否 | 0 至 100 | 維持原始圖像的結構（預設值：50）。 |
| `flavor` | COMBO | 否 | "faithful"<br>"gen_z"<br>"psychedelia"<br>"detaily"<br>"clear"<br>"donotstyle"<br>"donotstyle_sharp" | 風格轉換風味選項。 |
| `engine` | COMBO | 否 | "balanced"<br>"definio"<br>"illusio"<br>"3d_cartoon"<br>"colorful_anime"<br>"caricature"<br>"real"<br>"super_real"<br>"softy" | 處理引擎選擇。 |
| `portrait_mode` | COMBO | 否 | "disabled"<br>"enabled" | 啟用人像模式以進行臉部增強。 |
| `portrait_style` | COMBO | 否 | "standard"<br>"pop"<br>"super_pop" | 應用於人像圖像的視覺風格。此輸入僅在 `portrait_mode` 設為 "enabled" 時可用。 |
| `portrait_beautifier` | COMBO | 否 | "none"<br>"beautify_face"<br>"beautify_face_max" | 人像臉部美化強度。此輸入僅在 `portrait_mode` 設為 "enabled" 時可用。 |
| `fixed_generation` | BOOLEAN | 否 | - | 停用時，每次生成將引入一定程度的隨機性，從而產生更多樣化的結果（預設值：True）。 |

**限制條件：**

* 必須且僅能提供一個 `image` 和一個 `reference_image`。
* 兩個圖像的長寬比必須介於 1:3 至 3:1 之間。
* 兩個圖像的高度和寬度必須至少為 160 像素。
* `portrait_style` 和 `portrait_beautifier` 參數僅在 `portrait_mode` 設為 "enabled" 時才會啟用且為必填。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 套用風格轉換後產生的圖像。 |
