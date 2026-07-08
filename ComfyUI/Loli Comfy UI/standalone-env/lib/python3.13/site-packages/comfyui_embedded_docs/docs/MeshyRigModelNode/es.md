> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRigModelNode/es.md)

El nodo Meshy: Rig Model toma una tarea de modelo 3D de Meshy y genera un modelo de personaje con rig. Crea automáticamente un esqueleto para el modelo, permitiendo que sea posado y animado. El nodo devuelve el modelo con rig en los formatos de archivo GLB y FBX.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `meshy_task_id` | STRING | Sí | N/A | El ID único de tarea de una operación previa de Meshy (por ejemplo, texto-a-3D o imagen-a-3D) que generó el modelo al que se le aplicará el rig. |
| `height_meters` | FLOAT | Sí | 0.1 a 15.0 | La altura aproximada del modelo del personaje en metros. Ayuda en la precisión del escalado y la creación del rig (valor por defecto: 1.7). |
| `texture_image` | IMAGE | No | N/A | La imagen de textura de color base con UV-unwrapping del modelo. |

**Nota:** El proceso de auto-rigging actualmente no es adecuado para mallas sin textura, activos no humanoides o activos humanoides con una estructura de extremidades y cuerpo poco clara.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model_file` | STRING | Una salida heredada para compatibilidad con versiones anteriores, que contiene el nombre del archivo del modelo GLB. |
| `rig_task_id` | STRING | El ID único de tarea para esta operación de rigging, que puede usarse para referenciar el resultado. |
| `GLB` | FILE3DGLB | El modelo de personaje 3D con rig guardado en el formato de archivo GLB. |
| `FBX` | FILE3DFBX | El modelo de personaje 3D con rig guardado en el formato de archivo FBX. |
