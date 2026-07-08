> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/es.md)

El nodo **TextEncodeAceStepAudio1.5** prepara texto y metadatos relacionados con audio para su uso con el modelo AceStepAudio 1.5. Toma etiquetas descriptivas, letras y parámetros musicales, y luego utiliza un modelo CLIP para convertirlos en un formato de condicionamiento adecuado para la generación de audio.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Sí | N/A | El modelo CLIP utilizado para tokenizar y codificar el texto de entrada. |
| `tags` | STRING | Sí | N/A | Etiquetas descriptivas para el audio, como género, estado de ánimo o instrumentos. Admite entrada multilínea y prompts dinámicos. |
| `lyrics` | STRING | Sí | N/A | Las letras para la pista de audio. Admite entrada multilínea y prompts dinámicos. |
| `seed` | INT | No | 0 a 18446744073709551615 | Un valor de semilla aleatoria para una generación reproducible. Tiene un widget `control_after_generate`. Por defecto: 0. |
| `bpm` | INT | No | 10 a 300 | Los pulsos por minuto (BPM) para el audio generado. Por defecto: 120. |
| `duration` | FLOAT | No | 0.0 a 2000.0 | La duración deseada del audio en segundos. Por defecto: 120.0. |
| `timesignature` | COMBO | No | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | El compás musical. |
| `language` | COMBO | No | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | El idioma del texto de entrada. |
| `keyscale` | COMBO | No | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | La tonalidad y escala musical (mayor o menor). |
| `generate_audio_codes` | BOOLEAN | No | N/A | Activa el LLM que genera códigos de audio. Esto puede ser lento pero aumentará la calidad del audio generado. Desactívalo si le estás dando al modelo una referencia de audio. Por defecto: True. |
| `cfg_scale` | FLOAT | No | 0.0 a 100.0 | La escala de guía libre de clasificador. Valores más altos hacen que la salida siga más de cerca el prompt. Por defecto: 2.0. |
| `temperature` | FLOAT | No | 0.0 a 2.0 | Una temperatura de muestreo. Valores más bajos hacen que la salida sea más determinista. Por defecto: 0.85. |
| `top_p` | FLOAT | No | 0.0 a 2000.0 | La probabilidad de muestreo de núcleo (top-p). Por defecto: 0.9. |
| `top_k` | INT | No | 0 a 100 | El número de tokens de mayor probabilidad a considerar (top-k). Por defecto: 0. |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | Los datos de condicionamiento, que contienen el texto codificado y los parámetros de audio para el modelo AceStepAudio 1.5. |
