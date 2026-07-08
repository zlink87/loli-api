> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/RecraftCreateStyleNode/zh-TW.md)

此節點透過上傳參考圖片來建立用於圖片生成的自訂風格。您可以上傳 1 到 5 張圖片來定義新風格，節點將回傳一個唯一的風格 ID，此 ID 可與其他 Recraft 節點搭配使用。所有上傳圖片的總檔案大小不得超過 5 MB。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `style` | STRING | 是 | `"realistic_image"`<br>`"digital_illustration"` | 生成圖片的基礎風格。 |
| `images` | IMAGE | 是 | 1 到 5 張圖片 | 用於建立自訂風格的一組參考圖片，數量為 1 到 5 張。 |

**注意：** `images` 輸入中所有圖片的總檔案大小必須小於 5 MB。若超過此限制，節點將執行失敗。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `style_id` | STRING | 新建立的自訂風格之唯一識別碼。 |
