> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/CreateList/es.md)

El nodo Create List combina múltiples entradas en una sola lista secuencial. Toma cualquier número de entradas del mismo tipo de datos y las concatena en el orden en que están conectadas. Este nodo es útil para preparar lotes de datos, como imágenes o texto, para ser procesados por otros nodos en un flujo de trabajo.

## Entradas

| Parámetro | Tipo de Dato | Requerido | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `input_*` | Variable | Sí | Cualquiera | Un número variable de ranuras de entrada. Puedes agregar más entradas haciendo clic en el icono más (+). Todas las entradas deben ser del mismo tipo de datos (por ejemplo, todas IMAGE o todas STRING). |

**Nota:** El nodo creará automáticamente nuevas ranuras de entrada a medida que conectes elementos. Todas las entradas conectadas deben compartir el mismo tipo de datos para que el nodo funcione correctamente.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `list` | Variable | Una única lista que contiene todos los elementos de las entradas conectadas, concatenados en el orden en que fueron proporcionados. El tipo de dato de salida coincide con el tipo de dato de entrada. |
