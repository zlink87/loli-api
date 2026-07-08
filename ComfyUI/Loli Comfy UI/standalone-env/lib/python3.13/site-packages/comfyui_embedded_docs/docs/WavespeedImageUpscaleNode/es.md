> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedImageUpscaleNode/es.md)

El nodo WaveSpeed Image Upscale utiliza un servicio externo de IA para aumentar la resolución y calidad de una imagen. Toma una única foto de entrada y la escala a una resolución objetivo superior, como 2K, 4K u 8K, produciendo un resultado más nítido y detallado.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Sí | `"SeedVR2"`<br>`"Ultimate"` | El modelo de IA a utilizar para el escalado. "SeedVR2" y "Ultimate" ofrecen diferentes niveles de calidad y precios. |
| `image` | IMAGE | Sí | | La imagen de entrada que se va a escalar. |
| `target_resolution` | STRING | Sí | `"2K"`<br>`"4K"`<br>`"8K"` | La resolución de salida deseada para la imagen escalada. |

**Nota:** Este nodo requiere exactamente una imagen de entrada. Proporcionar un lote de imágenes resultará en un error.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen de salida escalada y de alta resolución. |
