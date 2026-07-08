> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedFlashVSRNode/zh-TW.md)

WavespeedFlashVSRNode 是一個快速、高品質的影片超解析度工具，能提升低解析度或模糊影片的解析度並恢復其清晰度。它處理輸入影片，並以使用者選擇的更高解析度輸出新的影片。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `video` | VIDEO | 是 | N/A | 要進行超解析度處理的輸入影片檔案。 |
| `target_resolution` | STRING | 是 | `"720p"`<br>`"1080p"`<br>`"2K"`<br>`"4K"` | 超解析度輸出影片所需的目標解析度。 |

**輸入限制：**

* 輸入的 `video` 檔案必須是 MP4 容器格式。
* 輸入 `video` 的持續時間必須在 5 秒到 10 分鐘（600 秒）之間。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `output` | VIDEO | 以所選目標解析度輸出的超解析度影片檔案。 |
