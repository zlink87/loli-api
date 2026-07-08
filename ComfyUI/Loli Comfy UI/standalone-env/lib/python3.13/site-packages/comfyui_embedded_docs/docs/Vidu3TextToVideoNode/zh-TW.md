> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3TextToVideoNode/zh-TW.md)

Vidu Q3 文字轉影片生成節點能根據文字描述建立影片。它使用 Vidu Q3 Pro 模型，依據您的提示生成影片內容，並允許您控制影片的長度、解析度和長寬比。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"viduq3-pro"` | 用於影片生成的模型。選擇此選項將顯示有關長寬比、解析度、持續時間和音訊的額外配置參數。 |
| `model.aspect_ratio` | COMBO | 是* | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | 輸出影片的長寬比。此參數在選擇 `model` 後顯示。 |
| `model.resolution` | COMBO | 是* | `"720p"`<br>`"1080p"` | 輸出影片的解析度。此參數在選擇 `model` 後顯示。 |
| `model.duration` | INT | 是* | 1 到 16 | 輸出影片的持續時間（單位：秒，預設值：5）。此參數在選擇 `model` 後顯示。 |
| `model.audio` | BOOLEAN | 是* | True/False | 啟用時，輸出帶有聲音（包括對話和音效）的影片（預設值：False）。此參數在選擇 `model` 後顯示。 |
| `prompt` | STRING | 是 | N/A | 用於影片生成的文字描述，最大長度為 2000 個字元。 |
| `seed` | INT | 否 | 0 到 2147483647 | 用於控制生成隨機性的種子值（預設值：1）。 |

*注意：一旦選擇了 `model`，參數 `aspect_ratio`、`resolution`、`duration` 和 `audio` 即為必填，因為它們是模型配置的一部分。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `video` | VIDEO | 生成的影片檔案。 |
