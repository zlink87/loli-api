> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ReferenceTimbreAudio/zh-TW.md)

此節點設定參考音色，用於「ace step 1.5」流程。它接收一個條件輸入，並可選擇性地接收一個音訊的潛在表示，然後將該潛在資料附加到條件資料上，供工作流程中的後續節點使用。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `conditioning` | CONDITIONING | 是 | | 將附加參考音訊資訊的條件資料。 |
| `latent` | LATENT | 否 | | 參考音訊的可選潛在表示。若提供，其樣本將被添加到條件資料中。 |

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `conditioning` | CONDITIONING | 修改後的條件資料。如果提供了可選的 `latent` 輸入，則現在包含參考音色的潛在資料。 |
