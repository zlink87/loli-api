> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokVideoEditNode/es.md)

Este nodo utiliza la API de Grok para editar un video existente basándose en un texto descriptivo. Sube tu video, envía una solicitud al modelo de IA para modificarlo según tu descripción y devuelve el video recién generado.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"grok-imagine-video-beta"` | El modelo de IA a utilizar para la edición de video. |
| `prompt` | STRING | Sí | N/A | Descripción textual del video deseado. |
| `video` | VIDEO | Sí | N/A | El video de entrada que se va a editar. La duración máxima admitida es de 8,7 segundos y el tamaño máximo del archivo es de 50 MB. |
| `seed` | INT | No | 0 a 2147483647 | Un valor de semilla para determinar si el nodo debe volver a ejecutarse. Los resultados reales son no deterministas independientemente del valor de la semilla (valor por defecto: 0). |

**Restricciones:**

* El `video` de entrada debe tener una duración entre 1 y 8,7 segundos.
* El tamaño del archivo del `video` de entrada no debe superar los 50 MB.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `video` | VIDEO | El video editado generado por el modelo de IA. |
