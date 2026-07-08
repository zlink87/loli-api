> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerCreativeNode/zh-TW.md)

此節點使用 Magnific AI 服務來放大並創意增強圖像。它允許您透過文字提示引導增強效果，選擇要優化的特定風格，並控制創意過程的各個方面，例如細節、與原始圖像的相似度以及風格化強度。該節點會輸出按您選擇的倍率（2倍、4倍、8倍或16倍）放大的圖像，最大輸出尺寸為 2530 萬像素。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | 是 | - | 要進行放大和增強處理的輸入圖像。 |
| `prompt` | STRING | 否 | - | 用於引導圖像創意增強的文字描述。此為可選項（預設值：空）。 |
| `scale_factor` | COMBO | 是 | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | 圖像尺寸的放大倍率。 |
| `optimized_for` | COMBO | 是 | `"standard"`<br>`"soft_portraits"`<br>`"hard_portraits"`<br>`"art_n_illustration"`<br>`"videogame_assets"`<br>`"nature_n_landscapes"`<br>`"films_n_photography"`<br>`"3d_renders"`<br>`"science_fiction_n_horror"` | 為增強處理過程進行優化的風格或內容類型。 |
| `creativity` | INT | 否 | -10 到 10 | 控制應用於圖像的創意詮釋程度（預設值：0）。 |
| `hdr` | INT | 否 | -10 到 10 | 定義和細節的等級（預設值：0）。 |
| `resemblance` | INT | 否 | -10 到 10 | 與原始圖像的相似度等級（預設值：0）。 |
| `fractality` | INT | 否 | -10 到 10 | 提示的強度以及每平方像素的複雜度（預設值：0）。 |
| `engine` | COMBO | 是 | `"automatic"`<br>`"magnific_illusio"`<br>`"magnific_sharpy"`<br>`"magnific_sparkle"` | 用於處理的特定 AI 引擎。 |
| `auto_downscale` | BOOLEAN | 否 | - | 啟用後，如果請求的放大倍率會超過允許的最大輸出尺寸 2530 萬像素，節點將自動縮小輸入圖像（預設值：False）。 |

**限制條件：**

* 輸入的 `image` 必須恰好是一張圖像。
* 輸入圖像的高度和寬度必須至少為 160 像素。
* 輸入圖像的長寬比必須介於 1:3 到 3:1 之間。
* 最終輸出尺寸（輸入尺寸乘以 `scale_factor`）不能超過 25,300,000 像素。如果 `auto_downscale` 被禁用且將超過此限制，節點將引發錯誤。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 經過創意增強和放大的輸出圖像。 |
