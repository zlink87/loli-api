> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/EmptyAceStep1.5LatentAudio/es.md)

El nodo Empty Ace Step 1.5 Latent Audio crea un tensor latente vacío diseñado para procesamiento de audio. Genera un latente de audio silencioso de una duración y tamaño de lote especificados, que puede utilizarse como punto de partida para flujos de trabajo de generación de audio en ComfyUI. El nodo calcula la longitud del latente en función de los segundos de entrada y una tasa de muestreo fija.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `seconds` | FLOAT | No | 1.0 - 1000.0 | La duración del audio a generar, en segundos (valor por defecto: 120.0). |
| `batch_size` | INT | No | 1 - 4096 | El número de imágenes latentes en el lote (valor por defecto: 1). |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `LATENT` | LATENT | Un tensor latente vacío que representa audio silencioso, con un identificador de tipo "audio". |
