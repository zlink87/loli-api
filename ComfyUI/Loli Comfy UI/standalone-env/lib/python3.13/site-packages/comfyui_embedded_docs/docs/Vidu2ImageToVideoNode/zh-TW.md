> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ImageToVideoNode/zh-TW.md)

Vidu2 圖像轉影片生成節點能從單一輸入圖像開始創建影片序列。它使用指定的 Vidu2 模型，根據可選的文字提示來為場景添加動畫，並控制影片的長度、解析度和運動強度。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | 用於影片生成的 Vidu2 模型。不同的模型在速度和品質之間有不同的權衡。 |
| `image` | IMAGE | 是 | - | 用作生成影片起始畫面的圖像。僅允許一張圖像。 |
| `prompt` | STRING | 否 | - | 用於影片生成的可選文字提示（最多 2000 個字元）。預設為空字串。 |
| `duration` | INT | 是 | 1 到 10 | 生成影片的長度（單位：秒）。預設為 5。 |
| `seed` | INT | 否 | 0 到 2147483647 | 用於隨機數生成的種子值，以確保結果可重現。預設為 1。 |
| `resolution` | COMBO | 是 | `"720p"`<br>`"1080p"` | 生成影片的輸出解析度。 |
| `movement_amplitude` | COMBO | 是 | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | 畫面中物體的運動幅度。 |

**限制條件：**

* `image` 輸入必須恰好包含一張圖像。
* 輸入圖像的長寬比必須在 1:4 到 4:1 之間。
* `prompt` 文字最多限制為 2000 個字元。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `output` | VIDEO | 生成的影片檔案。 |
