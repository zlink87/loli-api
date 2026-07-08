> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/es.md)

El nodo Meshy: Refine Draft Model toma un modelo 3D borrador generado previamente y mejora su calidad, añadiendo opcionalmente texturas. Envía una tarea de refinamiento a la API de Meshy y devuelve los archivos del modelo 3D final una vez completado el procesamiento.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"latest"` | Especifica el modelo de IA a utilizar para el refinamiento. Actualmente, solo está disponible el modelo "latest". |
| `meshy_task_id` | MESHY_TASK_ID | Sí | - | El ID único de la tarea del modelo borrador que se desea refinar. |
| `enable_pbr` | BOOLEAN | No | - | Generar mapas PBR (metálico, rugosidad, normal) además del color base. Nota: debe establecerse en false cuando se usa el estilo Sculpture, ya que este estilo genera su propio conjunto de mapas PBR. (por defecto: `False`) |
| `texture_prompt` | STRING | No | - | Proporciona un texto descriptivo para guiar el proceso de texturizado. Máximo 600 caracteres. No se puede usar al mismo tiempo que 'texture_image'. (por defecto: cadena vacía) |
| `texture_image` | IMAGE | No | - | Solo se puede usar uno de los dos, 'texture_image' o 'texture_prompt', al mismo tiempo. (opcional) |

**Nota:** Las entradas `texture_prompt` y `texture_image` son mutuamente excluyentes. No se puede proporcionar tanto un texto descriptivo como una imagen para el texturizado en la misma operación.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model_file` | STRING | El nombre del archivo del modelo GLB generado. (Solo para compatibilidad con versiones anteriores) |
| `meshy_task_id` | MESHY_TASK_ID | El ID único de la tarea para el trabajo de refinamiento enviado. |
| `GLB` | FILE3DGLB | El modelo 3D refinado final en formato GLB. |
| `FBX` | FILE3DFBX | El modelo 3D refinado final en formato FBX. |
