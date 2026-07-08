> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/es.md)

Este nodo mejora imágenes de baja resolución aumentándolas a superresolución, eliminando artefactos y ruido. Utiliza una API externa para procesar la imagen y puede ajustar automáticamente el tamaño de entrada para mantenerse dentro de los límites de procesamiento. El tamaño máximo permitido de salida es de 4 megapíxeles.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Sí | `"generative_portrait"`<br>`"generative"` | El modelo de mejora a utilizar. |
| `image` | IMAGE | Sí | - | La imagen de entrada que se va a mejorar. |
| `upscale_factor` | INT | Sí | `1`<br>`2`<br>`4` | El factor por el cual se aumentarán las dimensiones de la imagen. |
| `auto_downscale` | BOOLEAN | No | - | Reduce automáticamente la escala de la imagen de entrada si la salida excedería el límite. (por defecto: `False`) |

**Nota:** El nodo generará un error si el tamaño de salida calculado (altura de entrada × upscale_factor × ancho de entrada × upscale_factor) excede los 4,000,000 píxeles (4MP) y `auto_downscale` está desactivado. Cuando `auto_downscale` está activado, el nodo intentará reducir la escala de la imagen de entrada para que se ajuste al límite antes de aplicar el factor de aumento solicitado.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen de salida mejorada y aumentada en escala. |
