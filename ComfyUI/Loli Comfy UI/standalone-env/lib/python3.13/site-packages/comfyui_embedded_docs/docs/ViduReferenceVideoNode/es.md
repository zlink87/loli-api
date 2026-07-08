> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ViduReferenceVideoNode/es.md)

El nodo Vidu Reference Video genera videos a partir de múltiples imágenes de referencia y un texto descriptivo. Utiliza modelos de IA para crear contenido de video consistente basado en las imágenes proporcionadas y la descripción. El nodo admite varias configuraciones de video, incluyendo duración, relación de aspecto, resolución y control de movimiento.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"vidu_q1"` | Nombre del modelo para generación de video (por defecto: "vidu_q1") |
| `images` | IMAGE | Sí | - | Imágenes a utilizar como referencias para generar un video con sujetos consistentes (máximo 7 imágenes) |
| `prompt` | STRING | Sí | - | Descripción textual para la generación de video |
| `duration` | INT | No | 5-5 | Duración del video de salida en segundos (por defecto: 5) |
| `seed` | INT | No | 0-2147483647 | Semilla para la generación de video (0 para aleatorio) (por defecto: 0) |
| `aspect_ratio` | COMBO | No | `"16:9"`<br>`"9:16"`<br>`"1:1"`<br>`"4:3"`<br>`"3:4"`<br>`"21:9"`<br>`"9:21"` | La relación de aspecto del video de salida (por defecto: "16:9") |
| `resolution` | COMBO | No | `"480p"`<br>`"720p"`<br>`"1080p"`<br>`"1440p"`<br>`"2160p"` | Los valores admitidos pueden variar según el modelo y la duración (por defecto: "1080p") |
| `movement_amplitude` | COMBO | No | `"auto"`<br>`"low"`<br>`"medium"`<br>`"high"` | La amplitud de movimiento de los objetos en el cuadro (por defecto: "auto") |

**Restricciones y Limitaciones:**

- El campo `prompt` es obligatorio y no puede estar vacío
- Se permite un máximo de 7 imágenes como referencia
- Cada imagen debe tener una relación de aspecto entre 1:4 y 4:1
- Cada imagen debe tener dimensiones mínimas de 128x128 píxeles
- La duración está fijada en 5 segundos

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El video generado basado en las imágenes de referencia y el texto descriptivo |
