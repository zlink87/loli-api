> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedFlashVSRNode/es.md)

El WavespeedFlashVSRNode es un potente escalador de video rápido y de alta calidad que aumenta la resolución y restaura la nitidez de material de baja resolución o borroso. Procesa un video de entrada y genera un nuevo video en una resolución superior seleccionada por el usuario.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `video` | VIDEO | Sí | N/A | El archivo de video de entrada que se va a escalar. |
| `target_resolution` | STRING | Sí | `"720p"`<br>`"1080p"`<br>`"2K"`<br>`"4K"` | La resolución deseada para el video de salida escalado. |

**Restricciones de Entrada:**

* El archivo de entrada `video` debe estar en formato contenedor MP4.
* La duración del `video` de entrada debe estar entre 5 segundos y 10 minutos (600 segundos).

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | VIDEO | El archivo de video escalado en la resolución objetivo seleccionada. |
