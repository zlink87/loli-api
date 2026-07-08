> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2StartEndToVideoNode/es.md)

Este nodo genera un vídeo interpolando entre un fotograma inicial y un final proporcionados, guiado por un texto descriptivo. Utiliza un modelo Vidu especificado para crear una transición suave entre las dos imágenes durante una duración establecida.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | El modelo Vidu que se utilizará para la generación del vídeo. |
| `first_frame` | IMAGE | Sí | - | La imagen de inicio para la secuencia de vídeo. Solo se permite una única imagen. |
| `end_frame` | IMAGE | Sí | - | La imagen final para la secuencia de vídeo. Solo se permite una única imagen. |
| `prompt` | STRING | Sí | - | Una descripción textual que guía la generación del vídeo (máximo 2000 caracteres). |
| `duration` | INT | No | 2 a 8 | La duración del vídeo generado en segundos (por defecto: 5). |
| `seed` | INT | No | 0 a 2147483647 | Un número utilizado para inicializar la generación aleatoria y obtener resultados reproducibles (por defecto: 1). |
| `resolution` | COMBO | No | `"720p"`<br>`"1080p"` | La resolución de salida del vídeo generado. |
| `movement_amplitude` | COMBO | No | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | La amplitud del movimiento de los objetos en el fotograma. |

**Nota:** Las imágenes `first_frame` y `end_frame` deben tener proporciones de aspecto similares. El nodo validará que sus proporciones de aspecto estén dentro de un rango relativo de 0.8 a 1.25.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de vídeo generado. |
