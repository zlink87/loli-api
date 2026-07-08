> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageSkinEnhancerNode/es.md)

El nodo Magnific Image Skin Enhancer aplica un procesamiento especializado con IA a imágenes de retratos para mejorar la apariencia de la piel. Ofrece tres modos distintos para diferentes objetivos de mejora: creativo para efectos artísticos, fiel para preservar el aspecto original y flexible para mejoras específicas como iluminación o realismo. El nodo sube la imagen a una API externa para su procesamiento y devuelve el resultado mejorado.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Sí | - | La imagen de retrato a mejorar. |
| `sharpen` | INT | No | 0 a 100 | Nivel de intensidad del enfoque (valor por defecto: 0). |
| `smart_grain` | INT | No | 0 a 100 | Nivel de intensidad del grano inteligente (valor por defecto: 2). |
| `mode` | COMBO | Sí | `"creative"`<br>`"faithful"`<br>`"flexible"` | El modo de procesamiento a utilizar. `"creative"` es para mejora artística, `"faithful"` para preservar la apariencia original y `"flexible"` para optimización específica. |
| `skin_detail` | INT | No | 0 a 100 | Nivel de mejora del detalle de la piel. Esta entrada solo está disponible y es obligatoria cuando el `mode` está configurado en `"faithful"` (valor por defecto: 80). |
| `optimized_for` | COMBO | No | `"enhance_skin"`<br>`"improve_lighting"`<br>`"enhance_everything"`<br>`"transform_to_real"`<br>`"no_make_up"` | Objetivo de optimización de la mejora. Esta entrada solo está disponible y es obligatoria cuando el `mode` está configurado en `"flexible"`. |

**Restricciones:**

* El nodo acepta exactamente una imagen de entrada.
* La imagen de entrada debe tener una altura y un ancho mínimos de 160 píxeles.
* El parámetro `skin_detail` solo está activo cuando `mode` está configurado en `"faithful"`.
* El parámetro `optimized_for` solo está activo cuando `mode` está configurado en `"flexible"`.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen de retrato mejorada. |
