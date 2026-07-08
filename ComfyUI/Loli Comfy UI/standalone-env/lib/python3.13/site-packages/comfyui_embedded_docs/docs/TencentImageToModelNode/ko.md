> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/ko.md)

이 노드는 Tencent의 Hunyuan3D Pro API를 사용하여 하나 이상의 입력 이미지로부터 3D 모델을 생성합니다. 이미지를 처리하여 API로 전송하고, 생성된 3D 모델 파일을 GLB 및 OBJ 형식으로 반환합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | 예 | `"3.0"`<br>`"3.1"` | 사용할 Hunyuan3D 모델의 버전입니다. `3.1` 모델에서는 LowPoly 옵션을 사용할 수 없습니다. |
| `image` | IMAGE | 예 | - | 3D 모델 생성에 사용되는 주요 입력 이미지입니다. |
| `image_left` | IMAGE | 아니요 | - | 다중 뷰 생성을 위한 객체의 왼쪽 측면 이미지 (선택 사항). |
| `image_right` | IMAGE | 아니요 | - | 다중 뷰 생성을 위한 객체의 오른쪽 측면 이미지 (선택 사항). |
| `image_back` | IMAGE | 아니요 | - | 다중 뷰 생성을 위한 객체의 뒷면 이미지 (선택 사항). |
| `face_count` | INT | 예 | 40000 - 1500000 | 생성될 3D 모델의 목표 면(face) 수입니다 (기본값: 500000). |
| `generate_type` | DYNAMICCOMBO | 예 | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | 생성할 3D 모델의 유형입니다. 옵션을 선택하면 관련된 추가 매개변수가 표시됩니다. |
| `generate_type.pbr` | BOOLEAN | 아니요 | - | 물리 기반 렌더링(PBR) 재질 생성을 활성화합니다. 이 매개변수는 `generate_type`이 "Normal" 또는 "LowPoly"로 설정된 경우에만 표시됩니다 (기본값: False). |
| `generate_type.polygon_type` | COMBO | 아니요 | `"triangle"`<br>`"quadrilateral"` | 메시에 사용할 다각형의 유형입니다. 이 매개변수는 `generate_type`이 "LowPoly"로 설정된 경우에만 표시됩니다. |
| `seed` | INT | 예 | 0 - 2147483647 | 생성 프로세스를 위한 시드 값입니다. 시드는 노드를 재실행해야 하는지 여부를 제어하며, 결과는 시드와 관계없이 비결정적입니다 (기본값: 0). |

**참고:** 모든 입력 이미지는 너비와 높이가 최소 128픽셀이어야 합니다.

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `model_file` | STRING | 이전 버전과의 호환성을 위한 레거시 출력입니다. |
| `GLB` | FILE3DGLB | GLB(바이너리 GL 전송 형식) 파일 형식으로 생성된 3D 모델입니다. |
| `OBJ` | FILE3DOBJ | OBJ(Wavefront) 파일 형식으로 생성된 3D 모델입니다. |
