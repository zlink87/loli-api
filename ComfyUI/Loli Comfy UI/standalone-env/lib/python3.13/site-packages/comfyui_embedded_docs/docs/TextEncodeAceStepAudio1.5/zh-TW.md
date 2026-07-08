> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/zh-TW.md)

TextEncodeAceStepAudio1.5 節點負責為 AceStepAudio 1.5 模型準備文字和音訊相關的元數據。它接收描述性標籤、歌詞和音樂參數，然後使用 CLIP 模型將其轉換為適合音訊生成的條件化格式。

## 輸入參數

| 參數名稱 | 資料類型 | 必填 | 數值範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | 是 | 不適用 | 用於對輸入文字進行分詞和編碼的 CLIP 模型。 |
| `tags` | STRING | 是 | 不適用 | 音訊的描述性標籤，例如類型、情緒或樂器。支援多行輸入和動態提示詞。 |
| `lyrics` | STRING | 是 | 不適用 | 音訊軌道的歌詞。支援多行輸入和動態提示詞。 |
| `seed` | INT | 否 | 0 至 18446744073709551615 | 用於可重現生成的隨機種子值。帶有 control_after_generate 控制元件。預設值：0。 |
| `bpm` | INT | 否 | 10 至 300 | 生成音訊的每分鐘節拍數 (BPM)。預設值：120。 |
| `duration` | FLOAT | 否 | 0.0 至 2000.0 | 期望的音訊持續時間（單位：秒）。預設值：120.0。 |
| `timesignature` | COMBO | 否 | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | 音樂拍號。 |
| `language` | COMBO | 否 | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | 輸入文字的語言。 |
| `keyscale` | COMBO | 否 | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | 音樂調性和音階（大調或小調）。 |
| `generate_audio_codes` | BOOLEAN | 否 | 不適用 | 啟用生成音訊代碼的大型語言模型 (LLM)。這可能會較慢，但會提高生成音訊的品質。如果您向模型提供音訊參考，請關閉此選項。預設值：True。 |
| `cfg_scale` | FLOAT | 否 | 0.0 至 100.0 | 分類器自由引導尺度。數值越高，輸出越緊密遵循提示詞。預設值：2.0。 |
| `temperature` | FLOAT | 否 | 0.0 至 2.0 | 取樣溫度。數值越低，輸出越具確定性。預設值：0.85。 |
| `top_p` | FLOAT | 否 | 0.0 至 2000.0 | 核心取樣機率 (top-p)。預設值：0.9。 |
| `top_k` | INT | 否 | 0 至 100 | 要考慮的最高機率詞元數量 (top-k)。預設值：0。 |

## 輸出

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | 條件化數據，其中包含為 AceStepAudio 1.5 模型編碼的文字和音訊參數。 |
