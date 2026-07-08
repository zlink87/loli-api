> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyAnimateModelNode/es.md)

Este nodo aplica una animación específica a un modelo de personaje 3D que ya ha sido rigueado utilizando el servicio Meshy. Toma un ID de tarea de una operación de rigging previa y un ID de acción para seleccionar la animación deseada de la biblioteca. Luego, el nodo procesa la solicitud y devuelve el modelo animado en los formatos de archivo GLB y FBX.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `rig_task_id` | STRING | Sí | N/A | El ID de tarea único de una operación de rigging de personaje Meshy previamente completada. |
| `action_id` | INT | Sí | 0 a 696 | El número de ID de la acción de animación a aplicar. Visita <https://docs.meshy.ai/en/api/animation-library> para obtener una lista de valores disponibles. (por defecto: 0) |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model_file` | STRING | Un identificador de cadena para el modelo animado. Esta salida se proporciona únicamente por compatibilidad con versiones anteriores. |
| `GLB` | FILE3DGLB | El archivo del modelo 3D animado en formato GLB. |
| `FBX` | FILE3DFBX | El archivo del modelo 3D animado en formato FBX. |
