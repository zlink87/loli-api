> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageEditNode/zh-TW.md)

Grok Image Edit 節點會根據文字提示修改現有圖像。它使用 Grok API 生成一個或多個新圖像，這些圖像是輸入圖像的變體，並由您的描述引導生成。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"grok-imagine-image-beta"` | 用於圖像編輯的特定 AI 模型。 |
| `image` | IMAGE | 是 | | 要編輯的輸入圖像。僅支援單一圖像。 |
| `prompt` | STRING | 是 | | 用於生成編輯後圖像的文字提示。 |
| `resolution` | COMBO | 是 | `"1K"` | 輸出圖像的解析度。 |
| `number_of_images` | INT | 否 | 1 到 10 | 要生成的編輯圖像數量（預設值：1）。 |
| `seed` | INT | 否 | 0 到 2147483647 | 決定節點是否應重新執行的種子值；無論種子值為何，實際結果都是非確定性的（預設值：0）。 |

**注意：** `image` 輸入必須恰好包含一個圖像。提供多個圖像將導致錯誤。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `output` | IMAGE | 由節點生成的編輯後圖像。如果 `number_of_images` 大於 1，輸出將被串接成一個批次。 |
