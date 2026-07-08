> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3ImageToVideoNode/es.md)

El nodo Vidu Q3 Generación de Imagen a Video crea una secuencia de video a partir de una imagen de entrada. Utiliza el modelo Vidu Q3 Pro para animar la imagen, opcionalmente guiado por un texto descriptivo, y genera un archivo de video.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq3-pro"` | Modelo a utilizar para la generación de video. |
| `model.resolution` | COMBO | Sí | `"720p"`<br>`"1080p"`<br>`"2K"` | Resolución del video de salida. |
| `model.duration` | INT | Sí | 1 a 16 | Duración del video de salida en segundos (por defecto: 5). |
| `model.audio` | BOOLEAN | Sí | `True` / `False` | Cuando está habilitado, genera video con sonido (incluyendo diálogo y efectos de sonido) (por defecto: False). |
| `image` | IMAGE | Sí | - | Una imagen que se utilizará como el fotograma inicial del video generado. |
| `prompt` | STRING | No | - | Un texto descriptivo opcional para guiar la generación del video (máximo 2000 caracteres) (por defecto: vacío). |
| `seed` | INT | No | 0 a 2147483647 | Un valor de semilla para controlar la aleatoriedad de la generación (por defecto: 1). |

**Nota:** La `image` debe tener una relación de aspecto entre 1:4 y 4:1 (vertical a horizontal). El `prompt` es opcional pero no puede exceder los 2000 caracteres.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de video generado. |
