> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ViduExtendVideoNode/es.md)

El ViduExtendVideoNode genera fotogramas adicionales para extender la duración de un video existente. Utiliza un modelo de IA especificado para crear una continuación fluida basándose en el video fuente y en un mensaje de texto opcional.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq2-pro"`<br>`"viduq2-turbo"` | El modelo de IA a utilizar para la extensión del video. Al seleccionar un modelo, se revelan sus configuraciones específicas de duración y resolución. |
| `model.duration` | INT | Sí | 1 a 7 | La duración del video extendido en segundos (por defecto: 4). Esta configuración aparece después de seleccionar un modelo. |
| `model.resolution` | COMBO | Sí | `"720p"`<br>`"1080p"` | La resolución del video de salida. Esta configuración aparece después de seleccionar un modelo. |
| `video` | VIDEO | Sí | - | El video fuente que se va a extender. |
| `prompt` | STRING | No | - | Un mensaje de texto opcional para guiar el contenido del video extendido (máximo 2000 caracteres, por defecto: vacío). |
| `seed` | INT | No | 0 a 2147483647 | Un valor de semilla para controlar la aleatoriedad de la generación (por defecto: 1). |
| `end_frame` | IMAGE | No | - | Una imagen opcional para usar como fotograma final objetivo para la extensión. Si se proporciona, su relación de aspecto debe estar entre 1:4 y 4:1, y sus dimensiones deben ser de al menos 128x128 píxeles. |

**Nota:** El `video` fuente debe tener una duración entre 4 y 55 segundos.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de video recién generado que contiene las secuencias extendidas. |
