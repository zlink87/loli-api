> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WanInfiniteTalkToVideo/zh-TW.md)

WanInfiniteTalkToVideo 節點能從音訊輸入生成影片序列。它使用一個影片擴散模型，並以從一個或兩個說話者提取的音訊特徵為條件，來產生說話人頭像影片的潛在表示。此節點可以生成新的序列，或利用先前幀作為運動上下文來延伸現有序列。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 數值範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `mode` | COMBO | 是 | `"single_speaker"`<br>`"two_speakers"` | 音訊輸入模式。`"single_speaker"` 使用單一音訊輸入。`"two_speakers"` 啟用第二個說話者的輸入及對應遮罩。 |
| `model` | MODEL | 是 | - | 基礎影片擴散模型。 |
| `model_patch` | MODELPATCH | 是 | - | 包含音訊投影層的模型修補檔。 |
| `positive` | CONDITIONING | 是 | - | 用於引導生成的正向條件。 |
| `negative` | CONDITIONING | 是 | - | 用於引導生成的負向條件。 |
| `vae` | VAE | 是 | - | 用於將影像編碼至潛在空間及從中解碼的 VAE。 |
| `width` | INT | 否 | 16 - MAX_RESOLUTION | 輸出影片的寬度（像素）。必須能被 16 整除。（預設值：832） |
| `height` | INT | 否 | 16 - MAX_RESOLUTION | 輸出影片的高度（像素）。必須能被 16 整除。（預設值：480） |
| `length` | INT | 否 | 1 - MAX_RESOLUTION | 要生成的幀數。（預設值：81） |
| `clip_vision_output` | CLIPVISIONOUTPUT | 否 | - | 用於額外條件的可選 CLIP 視覺輸出。 |
| `start_image` | IMAGE | 否 | - | 用於初始化影片序列的可選起始影像。 |
| `audio_encoder_output_1` | AUDIOENCODEROUTPUT | 是 | - | 包含第一位說話者特徵的主要音訊編碼器輸出。 |
| `motion_frame_count` | INT | 否 | 1 - 33 | 延伸序列時，用作運動上下文的先前幀數。（預設值：9） |
| `audio_scale` | FLOAT | 否 | -10.0 - 10.0 | 應用於音訊條件的縮放因子。（預設值：1.0） |
| `previous_frames` | IMAGE | 否 | - | 用於延伸序列的可選先前影片幀。 |
| `audio_encoder_output_2` | AUDIOENCODEROUTPUT | 否 | - | 第二個音訊編碼器輸出。當 `mode` 設為 `"two_speakers"` 時為必填。 |
| `mask_1` | MASK | 否 | - | 第一位說話者的遮罩，使用兩個音訊輸入時為必填。 |
| `mask_2` | MASK | 否 | - | 第二位說話者的遮罩，使用兩個音訊輸入時為必填。 |

**參數約束：**

* 當 `mode` 設為 `"two_speakers"` 時，參數 `audio_encoder_output_2`、`mask_1` 和 `mask_2` 變為必填。
* 如果提供了 `audio_encoder_output_2`，則必須同時提供 `mask_1` 和 `mask_2`。
* 如果提供了 `mask_1` 和 `mask_2`，則必須同時提供 `audio_encoder_output_2`。
* 如果提供了 `previous_frames`，它必須包含至少與 `motion_frame_count` 指定數量相同的幀數。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model` | MODEL | 已套用音訊條件的修補後模型。 |
| `positive` | CONDITIONING | 正向條件，可能已根據額外上下文（例如起始影像、CLIP 視覺）進行修改。 |
| `negative` | CONDITIONING | 負向條件，可能已根據額外上下文進行修改。 |
| `latent` | LATENT | 潛在空間中生成的影片序列。 |
| `trim_image` | INT | 延伸序列時，應從運動上下文開頭修剪的幀數。 |
