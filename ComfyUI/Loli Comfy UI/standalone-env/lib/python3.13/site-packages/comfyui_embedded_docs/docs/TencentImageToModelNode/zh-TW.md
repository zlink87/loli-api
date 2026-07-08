> 本文檔由 AI 生成。如果您發現任何錯誤或有改進建議，歡迎貢獻！ [在 GitHub 上編輯](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/zh-TW.md)

此節點使用騰訊的 Hunyuan3D Pro API，從一張或多張輸入圖像生成 3D 模型。它會處理圖像，將其發送至 API，並以 GLB 和 OBJ 格式返回生成的 3D 模型檔案。

## 輸入參數

| 參數 | 資料類型 | 必填 | 範圍 | 描述 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 是 | `"3.0"`<br>`"3.1"` | 要使用的 Hunyuan3D 模型版本。`3.1` 模型不支援 LowPoly 選項。 |
| `image` | IMAGE | 是 | - | 用於生成 3D 模型的主要輸入圖像。 |
| `image_left` | IMAGE | 否 | - | 用於多視角生成的可選圖像，顯示物體的左側。 |
| `image_right` | IMAGE | 否 | - | 用於多視角生成的可選圖像，顯示物體的右側。 |
| `image_back` | IMAGE | 否 | - | 用於多視角生成的可選圖像，顯示物體的背面。 |
| `face_count` | INT | 是 | 40000 - 1500000 | 生成 3D 模型的目標面數（預設值：500000）。 |
| `generate_type` | DYNAMICCOMBO | 是 | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | 要生成的 3D 模型類型。選擇一個選項會顯示額外的相關參數。 |
| `generate_type.pbr` | BOOLEAN | 否 | - | 啟用基於物理的渲染 (PBR) 材質生成。此參數僅在 `generate_type` 設為 "Normal" 或 "LowPoly" 時可見（預設值：False）。 |
| `generate_type.polygon_type` | COMBO | 否 | `"triangle"`<br>`"quadrilateral"` | 用於網格的多邊形類型。此參數僅在 `generate_type` 設為 "LowPoly" 時可見。 |
| `seed` | INT | 是 | 0 - 2147483647 | 生成過程的種子值。種子控制節點是否應重新執行；無論種子為何，結果都是非確定性的（預設值：0）。 |

**注意：** 所有輸入圖像的寬度和高度必須至少為 128 像素。

## 輸出結果

| 輸出名稱 | 資料類型 | 描述 |
|-------------|-----------|-------------|
| `model_file` | STRING | 用於向後兼容的舊版輸出。 |
| `GLB` | FILE3DGLB | 以 GLB（二進位 GL 傳輸格式）檔案格式生成的 3D 模型。 |
| `OBJ` | FILE3DOBJ | 以 OBJ（Wavefront）檔案格式生成的 3D 模型。 |
