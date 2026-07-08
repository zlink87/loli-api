> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageRelightNode/ko.md)

Magnific Image Relight 노드는 입력 이미지의 조명을 조정합니다. 텍스트 프롬프트를 기반으로 스타일리시한 조명을 적용하거나, 선택적으로 제공된 참조 이미지의 조명 특성을 전달할 수 있습니다. 이 노드는 최종 출력물의 밝기, 대비 및 전체적인 분위기를 미세 조정하기 위한 다양한 제어 기능을 제공합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | 예 | 해당 없음 | 조명을 재조정할 이미지입니다. 정확히 하나의 이미지가 필요합니다. 최소 크기는 160x160 픽셀입니다. 종횡비는 1:3에서 3:1 사이여야 합니다. |
| `prompt` | STRING | 아니요 | 해당 없음 | 조명에 대한 설명적 지침입니다. 강조 표기법(1-1.4)을 지원합니다. 기본값은 빈 문자열입니다. |
| `light_transfer_strength` | INT | 예 | 0 ~ 100 | 조명 전달 적용 강도입니다. 기본값: 100. |
| `style` | COMBO | 예 | `"standard"`<br>`"darker_but_realistic"`<br>`"clean"`<br>`"smooth"`<br>`"brighter"`<br>`"contrasted_n_hdr"`<br>`"just_composition"` | 스타일리시한 출력 선호도입니다. |
| `interpolate_from_original` | BOOLEAN | 예 | 해당 없음 | 원본과 더 밀접하게 일치하도록 생성의 자유도를 제한합니다. 기본값: False. |
| `change_background` | BOOLEAN | 예 | 해당 없음 | 프롬프트/참조 이미지를 기반으로 배경을 수정합니다. 기본값: True. |
| `preserve_details` | BOOLEAN | 예 | 해당 없음 | 원본의 질감과 세부 사항을 유지합니다. 기본값: True. |
| `advanced_settings` | DYNAMICCOMBO | 예 | `"disabled"`<br>`"enabled"` | 고급 조명 제어를 위한 미세 조정 옵션입니다. `"enabled"`로 설정하면 추가 매개변수가 활성화됩니다. |
| `reference_image` | IMAGE | 아니요 | 해당 없음 | 조명을 전달할 선택적 참조 이미지입니다. 제공되는 경우 정확히 하나의 이미지가 필요합니다. 최소 크기는 160x160 픽셀입니다. 종횡비는 1:3에서 3:1 사이여야 합니다. |

**고급 설정 참고사항:** `advanced_settings`가 `"enabled"`로 설정되면 다음과 같은 중첩 매개변수가 활성화됩니다:

* `whites`: 이미지의 가장 밝은 톤을 조정합니다. 범위: 0 ~ 100. 기본값: 50.
* `blacks`: 이미지의 가장 어두운 톤을 조정합니다. 범위: 0 ~ 100. 기본값: 50.
* `brightness`: 전체 밝기 조정입니다. 범위: 0 ~ 100. 기본값: 50.
* `contrast`: 대비 조정입니다. 범위: 0 ~ 100. 기본값: 50.
* `saturation`: 색상 채도 조정입니다. 범위: 0 ~ 100. 기본값: 50.
* `engine`: 처리 엔진 선택입니다. 옵션: `"automatic"`, `"balanced"`, `"cool"`, `"real"`, `"illusio"`, `"fairy"`, `"colorful_anime"`, `"hard_transform"`, `"softy"`.
* `transfer_light_a`: 조명 전달의 강도입니다. 옵션: `"automatic"`, `"low"`, `"medium"`, `"normal"`, `"high"`, `"high_on_faces"`.
* `transfer_light_b`: 조명 전달 강도도 수정합니다. 이전 제어와 결합하여 다양한 효과를 낼 수 있습니다. 옵션: `"automatic"`, `"composition"`, `"straight"`, `"smooth_in"`, `"smooth_out"`, `"smooth_both"`, `"reverse_both"`, `"soft_in"`, `"soft_out"`, `"soft_mid"`, `"style_shift"`, `"strong_shift"`.
* `fixed_generation`: 동일한 설정으로 일관된 출력을 보장합니다. 기본값: True.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `image` | IMAGE | 조명이 재조정된 이미지입니다. |
