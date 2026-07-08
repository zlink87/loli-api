> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2TextToVideoNode/es.md)

El nodo Vidu2 Text-to-Video Generation crea un video a partir de una descripción de texto. Se conecta a una API externa para generar contenido de video basado en tu indicación, permitiéndote controlar la duración, el estilo visual y el formato del video.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"viduq2"` | El modelo de IA a utilizar para la generación de video. Actualmente, solo hay un modelo disponible. |
| `prompt` | STRING | Sí | - | Una descripción textual para la generación del video, con una longitud máxima de 2000 caracteres. |
| `duration` | INT | No | 1 a 10 | La duración del video generado en segundos. El valor se puede ajustar mediante un control deslizante (por defecto: 5). |
| `seed` | INT | No | 0 a 2147483647 | Un número utilizado para controlar la aleatoriedad de la generación, permitiendo resultados reproducibles. Se puede controlar después de la generación (por defecto: 1). |
| `aspect_ratio` | COMBO | No | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | La relación proporcional entre el ancho y la altura del video. |
| `resolution` | COMBO | No | `"720p"`<br>`"1080p"` | Las dimensiones en píxeles del video generado. |
| `background_music` | BOOLEAN | No | - | Indica si se debe añadir música de fondo al video generado (por defecto: Falso). |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de video generado. |
