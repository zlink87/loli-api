> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ReferenceVideoNode/es.md)

El nodo Vidu2 Reference-to-Video Generation crea un vídeo a partir de un texto descriptivo (prompt) y múltiples imágenes de referencia. Puedes definir hasta siete sujetos, cada uno con su propio conjunto de imágenes de referencia, y referenciarlos en el prompt usando `@subject{subject_id}`. El nodo genera un vídeo con duración, relación de aspecto y movimiento configurables.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq2"` | El modelo de IA que se utilizará para la generación del vídeo. |
| `subjects` | AUTOGROW | Sí | N/A | Para cada sujeto, proporciona hasta 3 imágenes de referencia (7 imágenes en total entre todos los sujetos). Referéncialos en los prompts mediante `@subject{subject_id}`. |
| `prompt` | STRING | Sí | N/A | La descripción textual utilizada para guiar la generación del vídeo. Cuando el parámetro `audio` está habilitado, el vídeo incluirá voz generada y música de fondo basada en este prompt. |
| `audio` | BOOLEAN | No | N/A | Cuando está habilitado, el vídeo contendrá voz generada y música de fondo basada en el prompt (por defecto: `False`). |
| `duration` | INT | No | 1 a 10 | La duración del vídeo generado en segundos (por defecto: `5`). |
| `seed` | INT | No | 0 a 2147483647 | Un número utilizado para controlar la aleatoriedad de la generación y obtener resultados reproducibles (por defecto: `1`). |
| `aspect_ratio` | COMBO | No | `"16:9"`<br>`"9:16"`<br>`"4:3"`<br>`"3:4"`<br>`"1:1"` | La forma del fotograma del vídeo. |
| `resolution` | COMBO | No | `"720p"`<br>`"1080p"` | La resolución en píxeles del vídeo de salida. |
| `movement_amplitude` | COMBO | No | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | Controla la amplitud del movimiento de los objetos en el fotograma. |

**Restricciones:**

* El `prompt` debe tener entre 1 y 2000 caracteres de longitud.
* Puedes definir múltiples sujetos, pero el número total de imágenes de referencia entre todos los sujetos no debe exceder de 7.
* Cada sujeto individual puede tener un máximo de 3 imágenes de referencia.
* Cada imagen de referencia debe tener una relación ancho-alto entre 1:4 y 4:1.
* Cada imagen de referencia debe tener al menos 128 píxeles tanto en ancho como en alto.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de vídeo generado. |
