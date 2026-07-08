> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/BriaImageEditNode/zh-TW.md)

Bria FIBO 影像編輯節點讓您能夠透過文字指令修改現有影像。它會將影像和您的提示詞傳送至 Bria API，該 API 使用 FIBO 模型根據您的要求生成新的、經過編輯的影像版本。您也可以提供遮罩，將編輯範圍限制在特定區域。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"FIBO"` | 用於影像編輯的模型版本。 |
| `image` | IMAGE | 是 | - | 您想要編輯的輸入影像。 |
| `prompt` | STRING | 否 | - | 描述如何編輯影像的文字指令（預設：空）。 |
| `negative_prompt` | STRING | 否 | - | 描述您不希望出現在編輯後影像中的內容的文字（預設：空）。 |
| `structured_prompt` | STRING | 否 | - | 一個包含 JSON 格式結構化編輯提示詞的字串。使用此參數代替常規提示詞，以實現精確的程式化控制（預設：空）。 |
| `seed` | INT | 是 | 1 至 2147483647 | 用於初始化隨機生成的數字，確保結果可重現（預設：1）。 |
| `guidance_scale` | FLOAT | 是 | 3.0 至 5.0 | 控制生成影像遵循提示詞的緊密程度。數值越高，遵循程度越強（預設：3.0）。 |
| `steps` | INT | 是 | 20 至 50 | 模型將執行的去噪步驟數量（預設：50）。 |
| `moderation` | DYNAMICCOMBO | 是 | `"true"`<br>`"false"` | 啟用或停用內容審核。選擇 `"true"` 會顯示額外的審核選項。 |
| `mask` | MASK | 否 | - | 可選的遮罩影像。如果提供，編輯將僅套用至影像的遮罩區域。 |

**重要限制：**

* 您必須至少提供 `prompt` 或 `structured_prompt` 其中一個輸入。兩者不能同時為空。
* 必須且僅能有一個輸入 `image`。
* 當 `moderation` 參數設為 `"true"` 時，會出現三個額外的布林值輸入：`prompt_content_moderation`、`visual_input_moderation` 和 `visual_output_moderation`。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `IMAGE` | IMAGE | 由 Bria API 返回的編輯後影像。 |
| `structured_prompt` | STRING | 在編輯過程中使用或生成的結構化提示詞。 |
