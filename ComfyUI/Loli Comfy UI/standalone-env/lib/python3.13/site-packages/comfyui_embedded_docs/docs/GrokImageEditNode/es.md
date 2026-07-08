> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageEditNode/es.md)

El nodo Grok Image Edit modifica una imagen existente basándose en un texto descriptivo. Utiliza la API de Grok para generar una o más imágenes nuevas que son variaciones de la entrada, guiadas por tu descripción.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"grok-imagine-image-beta"` | El modelo de IA específico a utilizar para la edición de imágenes. |
| `image` | IMAGE | Sí | | La imagen de entrada que se va a editar. Solo se admite una imagen. |
| `prompt` | STRING | Sí | | El texto descriptivo utilizado para generar la imagen editada. |
| `resolution` | COMBO | Sí | `"1K"` | La resolución para la imagen de salida. |
| `number_of_images` | INT | No | 1 a 10 | Número de imágenes editadas a generar (por defecto: 1). |
| `seed` | INT | No | 0 a 2147483647 | Semilla para determinar si el nodo debe volver a ejecutarse; los resultados reales son no deterministas independientemente de la semilla (por defecto: 0). |

**Nota:** La entrada `image` debe contener exactamente una imagen. Proporcionar múltiples imágenes causará un error.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | IMAGE | La(s) imagen(es) editada(s) generada(s) por el nodo. Si `number_of_images` es mayor que 1, las salidas se concatenan en un lote. |
