> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/ko.md)

이 노드는 저해상도 이미지를 초해상도로 업스케일하여 아티팩트와 노이즈를 제거합니다. 외부 API를 사용하여 이미지를 처리하며, 처리 제한 내에 머물도록 입력 크기를 자동으로 조정할 수 있습니다. 허용되는 최대 출력 크기는 4메가픽셀입니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | 예 | `"generative_portrait"`<br>`"generative"` | 사용할 향상 모델입니다. |
| `image` | IMAGE | 예 | - | 향상시킬 입력 이미지입니다. |
| `upscale_factor` | INT | 예 | `1`<br>`2`<br>`4` | 이미지 크기를 업스케일할 배율입니다. |
| `auto_downscale` | BOOLEAN | 아니요 | - | 출력이 제한을 초과할 경우 입력 이미지를 자동으로 다운스케일합니다. (기본값: `False`) |

**참고:** 계산된 출력 크기(입력 높이 × upscale_factor × 입력 너비 × upscale_factor)가 4,000,000 픽셀(4MP)을 초과하고 `auto_downscale`이 비활성화된 경우 노드는 오류를 발생시킵니다. `auto_downscale`이 활성화된 경우, 노드는 요청된 업스케일 배율을 적용하기 전에 제한 내에 맞도록 입력 이미지를 다운스케일하려고 시도합니다.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `image` | IMAGE | 향상되고 업스케일된 출력 이미지입니다. |
