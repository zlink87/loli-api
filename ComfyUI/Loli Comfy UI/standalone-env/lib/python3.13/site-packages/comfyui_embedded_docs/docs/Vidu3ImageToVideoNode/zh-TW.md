> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3ImageToVideoNode/zh-TW.md)

Vidu Q3 圖像轉影片生成節點能從輸入圖像開始創建影片序列。它使用 Vidu Q3 Pro 模型來為圖像添加動畫效果，可選擇性地透過文字提示引導，並輸出影片檔案。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"viduq3-pro"` | 用於影片生成的模型。 |
| `model.resolution` | COMBO | 是 | `"720p"`<br>`"1080p"`<br>`"2K"` | 輸出影片的解析度。 |
| `model.duration` | INT | 是 | 1 到 16 | 輸出影片的持續時間（單位：秒）（預設值：5）。 |
| `model.audio` | BOOLEAN | 是 | `True` / `False` | 啟用時，輸出帶有聲音（包括對話和音效）的影片（預設值：False）。 |
| `image` | IMAGE | 是 | - | 用作生成影片起始畫面的圖像。 |
| `prompt` | STRING | 否 | - | 用於影片生成的選填文字提示（最多 2000 個字元）（預設值：空）。 |
| `seed` | INT | 否 | 0 到 2147483647 | 用於控制生成隨機性的種子值（預設值：1）。 |

**注意：** `image` 的長寬比必須介於 1:4 到 4:1 之間（從直式到橫式）。`prompt` 為選填，但不能超過 2000 個字元。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `output` | VIDEO | 生成的影片檔案。 |
