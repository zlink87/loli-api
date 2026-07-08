> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3TextToVideoNode/es.md)

El nodo Vidu Q3 Text-to-Video Generation crea un video a partir de una descripción textual. Utiliza el modelo Vidu Q3 Pro para generar contenido de video basado en tu indicación, permitiéndote controlar la duración, resolución y relación de aspecto del video.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq3-pro"` | Modelo a utilizar para la generación de video. Seleccionar esta opción revela parámetros de configuración adicionales para la relación de aspecto, resolución, duración y audio. |
| `model.aspect_ratio` | COMBO | Sí* | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | La relación de aspecto del video de salida. Este parámetro se revela cuando se selecciona el `model`. |
| `model.resolution` | COMBO | Sí* | `"720p"`<br>`"1080p"` | Resolución del video de salida. Este parámetro se revela cuando se selecciona el `model`. |
| `model.duration` | INT | Sí* | 1 a 16 | Duración del video de salida en segundos (valor por defecto: 5). Este parámetro se revela cuando se selecciona el `model`. |
| `model.audio` | BOOLEAN | Sí* | Verdadero/Falso | Cuando está habilitado, genera un video con sonido (incluyendo diálogo y efectos de sonido) (valor por defecto: Falso). Este parámetro se revela cuando se selecciona el `model`. |
| `prompt` | STRING | Sí | N/A | Una descripción textual para la generación del video, con una longitud máxima de 2000 caracteres. |
| `seed` | INT | No | 0 a 2147483647 | Un valor de semilla para controlar la aleatoriedad de la generación (valor por defecto: 1). |

*Nota: Los parámetros `aspect_ratio`, `resolution`, `duration` y `audio` son obligatorios una vez seleccionado el `model`, ya que forman parte de su configuración.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `video` | VIDEO | El archivo de video generado. |
