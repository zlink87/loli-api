> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/es.md)

Este nodo utiliza la API Hunyuan3D Pro de Tencent para generar un modelo 3D a partir de una o más imágenes de entrada. Procesa las imágenes, las envía a la API y devuelve los archivos del modelo 3D generado en formatos GLB y OBJ.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"3.0"`<br>`"3.1"` | La versión del modelo Hunyuan3D a utilizar. La opción LowPoly no está disponible para el modelo `3.1`. |
| `image` | IMAGE | Sí | - | La imagen principal de entrada utilizada para generar el modelo 3D. |
| `image_left` | IMAGE | No | - | Una imagen opcional del lado izquierdo del objeto para generación multivista. |
| `image_right` | IMAGE | No | - | Una imagen opcional del lado derecho del objeto para generación multivista. |
| `image_back` | IMAGE | No | - | Una imagen opcional de la parte trasera del objeto para generación multivista. |
| `face_count` | INT | Sí | 40000 - 1500000 | El número objetivo de caras (faces) para el modelo 3D generado (por defecto: 500000). |
| `generate_type` | DYNAMICCOMBO | Sí | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | El tipo de modelo 3D a generar. Seleccionar una opción revela parámetros adicionales relacionados. |
| `generate_type.pbr` | BOOLEAN | No | - | Habilita la generación de materiales basados en renderizado físico (PBR). Este parámetro solo es visible cuando `generate_type` está configurado en "Normal" o "LowPoly" (por defecto: Falso). |
| `generate_type.polygon_type` | COMBO | No | `"triangle"`<br>`"quadrilateral"` | El tipo de polígono a utilizar para la malla. Este parámetro solo es visible cuando `generate_type` está configurado en "LowPoly". |
| `seed` | INT | Sí | 0 - 2147483647 | Un valor de semilla para el proceso de generación. La semilla controla si el nodo debe volver a ejecutarse; los resultados no son determinísticos independientemente de la semilla (por defecto: 0). |

**Nota:** Todas las imágenes de entrada deben tener un ancho y alto mínimo de 128 píxeles.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model_file` | STRING | Una salida heredada para compatibilidad con versiones anteriores. |
| `GLB` | FILE3DGLB | El modelo 3D generado en el formato de archivo GLB (Formato de Transmisión GL Binario). |
| `OBJ` | FILE3DOBJ | El modelo 3D generado en el formato de archivo OBJ (Wavefront). |
