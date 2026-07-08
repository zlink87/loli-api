> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/JoinAudioChannels/es.md)

El nodo Join Audio Channels combina dos entradas de audio mono separadas en una única salida de audio estéreo. Toma un canal izquierdo y un canal derecho, asegura que tengan frecuencias de muestreo y longitudes compatibles, y los fusiona en una forma de onda de audio de dos canales.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `audio_left` | AUDIO | Sí | | Los datos de audio mono que se utilizarán como canal izquierdo en el audio estéreo resultante. |
| `audio_right` | AUDIO | Sí | | Los datos de audio mono que se utilizarán como canal derecho en el audio estéreo resultante. |

**Nota:** Ambos flujos de audio de entrada deben ser mono (un solo canal). Si tienen frecuencias de muestreo diferentes, el canal con la frecuencia más baja se remuestreará automáticamente para igualar la más alta. Si los flujos de audio tienen longitudes diferentes, se recortarán a la longitud del más corto.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `audio` | AUDIO | El audio estéreo resultante, que contiene los canales izquierdo y derecho unidos. |
