> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawVideoEnhance/es.md)

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | DYNAMIC COMBO | Sí | Múltiples opciones disponibles | El modelo de IA que se utilizará para la mejora del vídeo. Al seleccionar un modelo se revela un parámetro anidado `resolution`. |
| `model.resolution` | COMBO | Sí | `"original"`<br>`"720p"`<br>`"1080p"`<br>`"2k/qhd"`<br>`"4k/uhd"`<br>`"8k"` | La resolución objetivo para el vídeo mejorado. Algunas opciones pueden no estar disponibles según el `model` seleccionado. |
| `video` | VIDEO | Sí | N/A | El archivo de vídeo de entrada que se va a mejorar. |

**Restricciones:**

* El `video` de entrada debe tener una duración entre 0.5 segundos y 60 minutos (3600 segundos).
* La `resolution` seleccionada debe ser mayor que las dimensiones del vídeo de entrada. Si el vídeo es cuadrado, la resolución seleccionada debe ser mayor que su ancho/alto. Para vídeos no cuadrados, la resolución seleccionada debe ser mayor que la dimensión más corta del vídeo. Si la resolución objetivo es menor, se generará un error. Elija `"original"` para mantener la resolución del vídeo de entrada.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `video` | VIDEO | El archivo de vídeo mejorado. |
