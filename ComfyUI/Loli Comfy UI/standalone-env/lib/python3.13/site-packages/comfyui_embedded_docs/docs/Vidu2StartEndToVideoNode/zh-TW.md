> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2StartEndToVideoNode/zh-TW.md)

此節點透過在提供的起始幀與結束幀之間進行插值，並以文字提示為引導來生成影片。它使用指定的 Vidu 模型，在設定的持續時間內於兩張圖像之間創建平滑的過渡。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | 用於影片生成的 Vidu 模型。 |
| `first_frame` | IMAGE | 是 | - | 影片序列的起始圖像。僅允許單張圖像。 |
| `end_frame` | IMAGE | 是 | - | 影片序列的結束圖像。僅允許單張圖像。 |
| `prompt` | STRING | 是 | - | 引導影片生成的文字描述（最多 2000 個字元）。 |
| `duration` | INT | 否 | 2 至 8 | 生成影片的長度（單位：秒，預設值：5）。 |
| `seed` | INT | 否 | 0 至 2147483647 | 用於初始化隨機生成以獲得可重現結果的數字（預設值：1）。 |
| `resolution` | COMBO | 否 | `"720p"`<br>`"1080p"` | 生成影片的輸出解析度。 |
| `movement_amplitude` | COMBO | 否 | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | 畫面中物體的運動幅度。 |

**注意：** `first_frame` 與 `end_frame` 圖像必須具有相似的長寬比。節點將驗證其長寬比是否在 0.8 至 1.25 的相對範圍內。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `output` | VIDEO | 生成的影片檔案。 |
