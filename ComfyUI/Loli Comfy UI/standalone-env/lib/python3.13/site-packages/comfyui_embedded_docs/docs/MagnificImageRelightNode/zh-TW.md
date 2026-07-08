> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageRelightNode/zh-TW.md)

Magnific Image Relight 節點可調整輸入圖像的照明效果。它能根據文字提示應用風格化照明，或從可選的參考圖像中轉移照明特性。此節點提供多種控制選項，用於微調最終輸出的亮度、對比度和整體氛圍。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 數值範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | 是 | N/A | 需要重新照明的圖像。必須提供恰好一張圖像。最小尺寸為 160x160 像素。長寬比必須介於 1:3 至 3:1 之間。 |
| `prompt` | STRING | 否 | N/A | 用於照明的描述性引導提示。支援強調符號 (1-1.4)。預設為空字串。 |
| `light_transfer_strength` | INT | 是 | 0 至 100 | 光線轉移應用的強度。預設值：100。 |
| `style` | COMBO | 是 | `"standard"`<br>`"darker_but_realistic"`<br>`"clean"`<br>`"smooth"`<br>`"brighter"`<br>`"contrasted_n_hdr"`<br>`"just_composition"` | 風格化輸出偏好。 |
| `interpolate_from_original` | BOOLEAN | 是 | N/A | 限制生成自由度，使其更貼近原始圖像。預設值：False。 |
| `change_background` | BOOLEAN | 是 | N/A | 根據提示或參考圖像修改背景。預設值：True。 |
| `preserve_details` | BOOLEAN | 是 | N/A | 保留原始圖像的紋理和細節。預設值：True。 |
| `advanced_settings` | DYNAMICCOMBO | 是 | `"disabled"`<br>`"enabled"` | 用於進階照明控制的微調選項。設定為 `"enabled"` 時，將啟用額外參數。 |
| `reference_image` | IMAGE | 否 | N/A | 用於轉移照明的可選參考圖像。若提供，必須恰好一張圖像。最小尺寸為 160x160 像素。長寬比必須介於 1:3 至 3:1 之間。 |

**關於進階設定的說明：** 當 `advanced_settings` 設定為 `"enabled"` 時，以下嵌套參數將被啟用：

* `whites`：調整圖像中最亮的色調。範圍：0 至 100。預設值：50。
* `blacks`：調整圖像中最暗的色調。範圍：0 至 100。預設值：50。
* `brightness`：整體亮度調整。範圍：0 至 100。預設值：50。
* `contrast`：對比度調整。範圍：0 至 100。預設值：50。
* `saturation`：色彩飽和度調整。範圍：0 至 100。預設值：50。
* `engine`：處理引擎選擇。選項：`"automatic"`、`"balanced"`、`"cool"`、`"real"`、`"illusio"`、`"fairy"`、`"colorful_anime"`、`"hard_transform"`、`"softy"`。
* `transfer_light_a`：光線轉移的強度。選項：`"automatic"`、`"low"`、`"medium"`、`"normal"`、`"high"`、`"high_on_faces"`。
* `transfer_light_b`：同樣修改光線轉移強度。可與前一個控制項結合以產生不同效果。選項：`"automatic"`、`"composition"`、`"straight"`、`"smooth_in"`、`"smooth_out"`、`"smooth_both"`、`"reverse_both"`、`"soft_in"`、`"soft_out"`、`"soft_mid"`、`"style_shift"`、`"strong_shift"`。
* `fixed_generation`：確保使用相同設定時輸出結果一致。預設值：True。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `image` | IMAGE | 重新照明後的圖像。 |
