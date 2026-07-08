> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypass/ko.md)

LoraLoaderBypass 노드는 LoRA(Low-Rank Adaptation)를 확산 모델과 CLIP 모델에 특별한 "바이패스" 모드로 적용합니다. 표준 LoRA 로더와 달리, 이 방법은 기본 모델의 가중치를 영구적으로 수정하지 않습니다. 대신, 모델의 정상적인 순전파 과정에 LoRA의 효과를 더하여 출력을 계산하는 방식으로, 모델 학습 시나 가중치가 오프로드된 모델을 작업할 때 유용합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | 예 | - | LoRA가 적용될 확산 모델입니다. |
| `clip` | CLIP | 예 | - | LoRA가 적용될 CLIP 모델입니다. |
| `lora_name` | COMBO | 예 | *사용 가능한 LoRA 파일 목록* | 적용할 LoRA 파일의 이름입니다. 옵션은 `loras` 폴더에서 로드됩니다. |
| `strength_model` | FLOAT | 예 | -100.0 ~ 100.0 | 확산 모델을 수정할 강도입니다. 이 값은 음수일 수 있습니다 (기본값: 1.0). |
| `strength_clip` | FLOAT | 예 | -100.0 ~ 100.0 | CLIP 모델을 수정할 강도입니다. 이 값은 음수일 수 있습니다 (기본값: 1.0). |

**참고:** `strength_model`과 `strength_clip`이 모두 0으로 설정되면, 이 노드는 처리 없이 원본의 수정되지 않은 `model`과 `clip` 입력을 반환합니다.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `MODEL` | MODEL | 바이패스 모드로 LoRA가 적용된 확산 모델입니다. |
| `CLIP` | CLIP | 바이패스 모드로 LoRA가 적용된 CLIP 모델입니다. |
