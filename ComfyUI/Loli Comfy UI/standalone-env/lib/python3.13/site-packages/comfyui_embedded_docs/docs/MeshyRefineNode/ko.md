> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/ko.md)

Meshy: Refine Draft Model 노드는 이전에 생성된 3D 드래프트 모델을 가져와 품질을 개선하고, 선택적으로 텍스처를 추가합니다. Meshy API에 리파인먼트 작업을 제출하고 처리가 완료되면 최종 3D 모델 파일을 반환합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 예 | `"latest"` | 리파인먼트에 사용할 AI 모델을 지정합니다. 현재는 "latest" 모델만 사용 가능합니다. |
| `meshy_task_id` | MESHY_TASK_ID | 예 | - | 리파인먼트하려는 드래프트 모델의 고유 작업 ID입니다. |
| `enable_pbr` | BOOLEAN | 아니오 | - | 기본 색상 외에 PBR 맵(메탈릭, 러프니스, 노멀)을 생성합니다. 참고: Sculpture 스타일을 사용할 때는 이 옵션을 false로 설정해야 합니다. Sculpture 스타일은 자체 PBR 맵 세트를 생성하기 때문입니다. (기본값: `False`) |
| `texture_prompt` | STRING | 아니오 | - | 텍스처링 과정을 안내하는 텍스트 프롬프트를 제공합니다. 최대 600자. 'texture_image'와 동시에 사용할 수 없습니다. (기본값: 빈 문자열) |
| `texture_image` | IMAGE | 아니오 | - | 'texture_image'와 'texture_prompt' 중 하나만 동시에 사용할 수 있습니다. (선택 사항) |

**참고:** `texture_prompt`와 `texture_image` 입력은 상호 배타적입니다. 동일한 작업에서 텍스처링을 위한 텍스트 프롬프트와 이미지를 모두 제공할 수 없습니다.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `model_file` | STRING | 생성된 GLB 모델의 파일명입니다. (하위 호환성 전용) |
| `meshy_task_id` | MESHY_TASK_ID | 제출된 리파인먼트 작업의 고유 작업 ID입니다. |
| `GLB` | FILE3DGLB | GLB 형식의 최종 리파인된 3D 모델입니다. |
| `FBX` | FILE3DFBX | FBX 형식의 최종 리파인된 3D 모델입니다. |
