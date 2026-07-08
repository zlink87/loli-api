> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedImageUpscaleNode/ko.md)

WaveSpeed Image Upscale 노드는 외부 AI 서비스를 사용하여 이미지의 해상도와 품질을 향상시킵니다. 단일 입력 사진을 받아 2K, 4K, 8K와 같은 더 높은 목표 해상도로 업스케일하여 더 선명하고 디테일한 결과물을 생성합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | 예 | `"SeedVR2"`<br>`"Ultimate"` | 업스케일에 사용할 AI 모델입니다. "SeedVR2"와 "Ultimate"는 서로 다른 품질과 가격대를 제공합니다. |
| `image` | IMAGE | 예 | | 업스케일할 입력 이미지입니다. |
| `target_resolution` | STRING | 예 | `"2K"`<br>`"4K"`<br>`"8K"` | 업스케일된 이미지에 원하는 출력 해상도입니다. |

**참고:** 이 노드는 정확히 하나의 입력 이미지만 필요로 합니다. 여러 이미지를 배치로 제공하면 오류가 발생합니다.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `image` | IMAGE | 업스케일된 고해상도 출력 이미지입니다. |
