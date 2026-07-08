> 이 문서는 AI에 의해 생성되었습니다. 오류를 발견하거나 개선 제안이 있으시면 기여해 주세요! [GitHub에서 편집](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/ko.md)

TextEncodeAceStepAudio1.5 노드는 AceStepAudio 1.5 모델에서 사용하기 위해 텍스트와 오디오 관련 메타데이터를 준비합니다. 설명 태그, 가사, 음악적 매개변수를 입력받아 CLIP 모델을 사용하여 오디오 생성에 적합한 조건부 형식으로 변환합니다.

## 입력

| 매개변수 | 데이터 타입 | 필수 | 범위 | 설명 |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | 예 | 해당 없음 | 입력 텍스트를 토큰화하고 인코딩하는 데 사용되는 CLIP 모델입니다. |
| `tags` | STRING | 예 | 해당 없음 | 장르, 분위기, 악기 등 오디오에 대한 설명 태그입니다. 여러 줄 입력과 동적 프롬프트를 지원합니다. |
| `lyrics` | STRING | 예 | 해당 없음 | 오디오 트랙의 가사입니다. 여러 줄 입력과 동적 프롬프트를 지원합니다. |
| `seed` | INT | 아니요 | 0 ~ 18446744073709551615 | 재현 가능한 생성을 위한 난수 시드 값입니다. control_after_generate 위젯이 있습니다. 기본값: 0. |
| `bpm` | INT | 아니요 | 10 ~ 300 | 생성될 오디오의 분당 비트 수(BPM)입니다. 기본값: 120. |
| `duration` | FLOAT | 아니요 | 0.0 ~ 2000.0 | 원하는 오디오의 길이(초)입니다. 기본값: 120.0. |
| `timesignature` | COMBO | 아니요 | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | 음악적 박자표입니다. |
| `language` | COMBO | 아니요 | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | 입력 텍스트의 언어입니다. |
| `keyscale` | COMBO | 아니요 | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | 음악적 조성과 스케일(장조 또는 단조)입니다. |
| `generate_audio_codes` | BOOLEAN | 아니요 | 해당 없음 | 오디오 코드를 생성하는 LLM을 활성화합니다. 느릴 수 있지만 생성된 오디오의 품질을 높입니다. 모델에 오디오 참조를 제공하는 경우에는 끄세요. 기본값: True. |
| `cfg_scale` | FLOAT | 아니요 | 0.0 ~ 100.0 | 분류기 없는 지도 척도입니다. 값이 높을수록 출력이 프롬프트를 더 밀접하게 따릅니다. 기본값: 2.0. |
| `temperature` | FLOAT | 아니요 | 0.0 ~ 2.0 | 샘플링 온도입니다. 값이 낮을수록 출력이 더 결정적이 됩니다. 기본값: 0.85. |
| `top_p` | FLOAT | 아니요 | 0.0 ~ 2000.0 | 핵 샘플링 확률(top-p)입니다. 기본값: 0.9. |
| `top_k` | INT | 아니요 | 0 ~ 100 | 고려할 가장 높은 확률 토큰의 수(top-k)입니다. 기본값: 0. |

## 출력

| 출력 이름 | 데이터 타입 | 설명 |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | AceStepAudio 1.5 모델을 위한 인코딩된 텍스트와 오디오 매개변수를 포함하는 조건부 데이터입니다. |
