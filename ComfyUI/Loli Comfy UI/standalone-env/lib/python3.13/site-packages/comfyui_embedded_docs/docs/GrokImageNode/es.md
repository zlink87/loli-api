> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageNode/es.md)

El nodo Grok Image genera una o más imágenes basadas en una descripción de texto utilizando el modelo de IA Grok. Envía su *prompt* a un servicio externo y devuelve las imágenes generadas como tensores que pueden usarse en su flujo de trabajo.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"grok-imagine-image-beta"` | El modelo específico de Grok a utilizar para la generación de imágenes. |
| `prompt` | STRING | Sí | N/A | El *prompt* de texto utilizado para generar la imagen. Esta descripción guía a la IA sobre qué crear. |
| `aspect_ratio` | COMBO | Sí | `"1:1"`<br>`"2:3"`<br>`"3:2"`<br>`"3:4"`<br>`"4:3"`<br>`"9:16"`<br>`"16:9"`<br>`"9:19.5"`<br>`"19.5:9"`<br>`"9:20"`<br>`"20:9"`<br>`"1:2"`<br>`"2:1"` | La relación ancho-alto deseada para la imagen generada. |
| `number_of_images` | INT | No | 1 a 10 | Número de imágenes a generar (por defecto: 1). |
| `seed` | INT | No | 0 a 2147483647 | Un valor de semilla para determinar si el nodo debe volver a ejecutarse. Los resultados reales de la imagen son no deterministas y variarán incluso con la misma semilla (por defecto: 0). |

**Nota:** El parámetro `seed` se utiliza principalmente para controlar cuándo se re-ejecuta el nodo dentro de un flujo de trabajo. Debido a la naturaleza del servicio de IA externo, las imágenes generadas no serán reproducibles ni idénticas entre ejecuciones, incluso con una semilla idéntica.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | IMAGE | La imagen generada o un lote de imágenes. Si `number_of_images` es 1, se devuelve un único tensor de imagen. Si es mayor que 1, se devuelve un lote de tensores de imagen. |
