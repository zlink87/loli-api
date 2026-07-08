> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyMultiImageToModelNode/es.md)

Este nodo utiliza la API de Meshy para generar un modelo 3D a partir de múltiples imágenes de entrada. Sube las imágenes proporcionadas, envía una tarea de procesamiento y devuelve los archivos del modelo 3D resultante (GLB y FBX) junto con el ID de la tarea para referencia.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
| :--- | :--- | :--- | :--- | :--- |
| `model` | COMBO | Sí | `"latest"` | Especifica la versión del modelo de IA a utilizar. |
| `images` | IMAGE | Sí | 2 a 4 imágenes | Un conjunto de imágenes utilizado para generar el modelo 3D. Debes proporcionar entre 2 y 4 imágenes. |
| `should_remesh` | COMBO | Sí | `"true"`<br>`"false"` | Determina si la malla generada debe ser procesada. Cuando se establece en `"false"`, el nodo devuelve una malla triangular sin procesar. |
| `topology` | COMBO | No | `"triangle"`<br>`"quad"` | El tipo de polígono objetivo para la salida remallada. Este parámetro solo está disponible y es obligatorio cuando `should_remesh` está establecido en `"true"`. |
| `target_polycount` | INT | No | 100 a 300000 | El número objetivo de polígonos para el modelo remallado (por defecto: 300000). Este parámetro solo está disponible cuando `should_remesh` está establecido en `"true"`. |
| `symmetry_mode` | COMBO | Sí | `"auto"`<br>`"on"`<br>`"off"` | Controla si se aplica simetría al modelo generado. |
| `should_texture` | COMBO | Sí | `"true"`<br>`"false"` | Determina si se generan texturas. Establecerlo en `"false"` omite la fase de texturizado y devuelve una malla sin texturas. |
| `enable_pbr` | BOOLEAN | No | `True` / `False` | Cuando `should_texture` es `"true"`, esta opción genera Mapas PBR (metálico, rugosidad, normal) además del color base (por defecto: `False`). |
| `texture_prompt` | STRING | No | - | Un texto descriptivo para guiar el proceso de texturizado (máximo 600 caracteres). No se puede usar al mismo tiempo que `texture_image`. Este parámetro solo está disponible cuando `should_texture` está establecido en `"true"`. |
| `texture_image` | IMAGE | No | - | Una imagen para guiar el proceso de texturizado. Solo se puede usar una de las opciones, `texture_image` o `texture_prompt`, al mismo tiempo. Este parámetro solo está disponible cuando `should_texture` está establecido en `"true"`. |
| `pose_mode` | COMBO | Sí | `""`<br>`"A-pose"`<br>`"T-pose"` | Especifica el modo de pose para el modelo generado. |
| `seed` | INT | Sí | 0 a 2147483647 | Un valor de semilla para el proceso de generación (por defecto: 0). Los resultados no son deterministas independientemente de la semilla, pero cambiar la semilla puede hacer que el nodo se vuelva a ejecutar. |

**Restricciones de Parámetros:**

* Debes proporcionar entre 2 y 4 imágenes para la entrada `images`.
* Los parámetros `topology` y `target_polycount` solo están activos cuando `should_remesh` está establecido en `"true"`.
* Los parámetros `enable_pbr`, `texture_prompt` y `texture_image` solo están activos cuando `should_texture` está establecido en `"true"`.
* No puedes usar `texture_prompt` y `texture_image` al mismo tiempo; son mutuamente excluyentes.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
| :--- | :--- | :--- |
| `model_file` | STRING | El nombre del archivo del modelo GLB generado. Esta salida se proporciona por compatibilidad con versiones anteriores. |
| `meshy_task_id` | MESHY_TASK_ID | El identificador único para la tarea de la API de Meshy. |
| `GLB` | FILE3DGLB | El modelo 3D generado en formato GLB. |
| `FBX` | FILE3DFBX | El modelo 3D generado en formato FBX. |
