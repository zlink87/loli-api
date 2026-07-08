> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextureNode/es.md)

El nodo Meshy: Texture aplica texturas generadas por IA a un modelo 3D. Toma un ID de tarea de un nodo previo de generación o conversión 3D de Meshy y utiliza una descripción de texto o una imagen de referencia para crear nuevas texturas para el modelo. El nodo devuelve el modelo texturizado en los formatos de archivo GLB y FBX.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"latest"` | La versión del modelo de IA a utilizar para el texturizado. Actualmente, solo está disponible la versión "latest". |
| `meshy_task_id` | MESHY_TASK_ID | Sí | - | El identificador único (ID de tarea) de una tarea previa de generación o conversión 3D de Meshy. Proporciona el modelo 3D base que se va a texturizar. |
| `enable_original_uv` | BOOLEAN | No | - | Cuando está habilitado (por defecto: `True`), el nodo utiliza el diseño UV original del modelo cargado, preservando cualquier textura existente. Si el modelo no tiene un UV original, la calidad de salida puede ser menor. |
| `pbr` | BOOLEAN | No | - | Habilita la salida de materiales de Renderizado Basado en Física (PBR) para el modelo texturizado (por defecto: `False`). |
| `text_style_prompt` | STRING | No | - | Una descripción de texto del estilo de textura deseado para el objeto. Máximo 600 caracteres. No se puede usar al mismo tiempo que `image_style`. |
| `image_style` | IMAGE | No | - | Una imagen de referencia 2D para guiar el proceso de texturizado. No se puede usar al mismo tiempo que `text_style_prompt`. |

**Restricciones de Parámetros:**

* Debes proporcionar un `text_style_prompt` o un `image_style`, pero no puedes proporcionar ambos al mismo tiempo.
* El `text_style_prompt` está limitado a un máximo de 600 caracteres.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model_file` | STRING | El nombre del archivo del modelo GLB generado. Esta salida se proporciona para compatibilidad con versiones anteriores. |
| `meshy_task_id` | MODEL_TASK_ID | El identificador único de tarea para este trabajo de texturizado, que puede usarse para referenciar el resultado. |
| `GLB` | FILE3DGLB | El modelo 3D texturizado guardado en el formato de archivo GLB. |
| `FBX` | FILE3DFBX | El modelo 3D texturizado guardado en el formato de archivo FBX. |
