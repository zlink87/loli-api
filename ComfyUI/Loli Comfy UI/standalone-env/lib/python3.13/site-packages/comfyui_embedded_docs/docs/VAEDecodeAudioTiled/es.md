> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/VAEDecodeAudioTiled/es.md)

Este nodo convierte una representación de audio comprimida (muestras latentes) de vuelta a una forma de onda de audio utilizando un Autoencoder Variacional (VAE). Procesa los datos en secciones más pequeñas y superpuestas (baldosas o *tiles*) para gestionar el uso de memoria, lo que lo hace adecuado para manejar secuencias de audio más largas.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `samples` | LATENT | Sí | N/A | La representación latente comprimida del audio que se va a decodificar. |
| `vae` | VAE | Sí | N/A | El modelo de Autoencoder Variacional utilizado para realizar la decodificación. |
| `tile_size` | INT | No | 32 a 8192 | El tamaño de cada baldosa de procesamiento. El audio se decodifica en secciones de esta longitud para conservar memoria (por defecto: 512). |
| `overlap` | INT | No | 0 a 1024 | El número de muestras que se superponen las baldosas adyacentes. Esto ayuda a reducir artefactos en los límites entre baldosas (por defecto: 64). |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `output` | AUDIO | La forma de onda de audio decodificada. |
