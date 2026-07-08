> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ReferenceTimbreAudio/es.md)

Este nodo establece un timbre de audio de referencia para su uso en el proceso "ace step 1.5". Funciona tomando una entrada de acondicionamiento y, opcionalmente, una representación latente de audio, y luego adjunta esos datos latentes al acondicionamiento para que los nodos posteriores en el flujo de trabajo los utilicen.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `conditioning` | CONDITIONING | Sí | | Los datos de acondicionamiento a los que se adjuntará la información de audio de referencia. |
| `latent` | LATENT | No | | Una representación latente opcional del audio de referencia. Cuando se proporciona, sus muestras se añaden al acondicionamiento. |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `conditioning` | CONDITIONING | Los datos de acondicionamiento modificados, que ahora contienen los latentes del timbre de audio de referencia si se proporcionó la entrada opcional `latent`. |
