> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeZImageOmni/es.md)

El nodo TextEncodeZImageOmni es un nodo de acondicionamiento avanzado que codifica un *prompt* de texto junto con imágenes de referencia opcionales en un formato de acondicionamiento adecuado para modelos de generación de imágenes. Puede procesar hasta tres imágenes, codificándolas opcionalmente con un codificador visual y/o un VAE para producir latentes de referencia, e integra estas referencias visuales con el *prompt* de texto utilizando una estructura de plantilla específica.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Sí | | El modelo CLIP utilizado para tokenizar y codificar el *prompt* de texto. |
| `image_encoder` | CLIPVision | No | | Un modelo codificador visual opcional. Si se proporciona, se utilizará para codificar las imágenes de entrada, y los *embeddings* resultantes se añadirán al acondicionamiento. |
| `prompt` | STRING | Sí | | El *prompt* de texto que se va a codificar. Este campo admite entrada multilínea y *prompts* dinámicos. |
| `auto_resize_images` | BOOLEAN | No | | Cuando está habilitado (por defecto: True), las imágenes de entrada se redimensionarán automáticamente en función de su área de píxeles antes de pasarse al VAE para su codificación. |
| `vae` | VAE | No | | Un modelo VAE opcional. Si se proporciona, se utilizará para codificar las imágenes de entrada en representaciones latentes, que se añaden al acondicionamiento como latentes de referencia. |
| `image1` | IMAGE | No | | La primera imagen de referencia opcional. |
| `image2` | IMAGE | No | | La segunda imagen de referencia opcional. |
| `image3` | IMAGE | No | | La tercera imagen de referencia opcional. |

**Nota:** El nodo puede aceptar un máximo de tres imágenes (`image1`, `image2`, `image3`). Las entradas `image_encoder` y `vae` solo se utilizan si se proporciona al menos una imagen. Cuando `auto_resize_images` es True y un `vae` está conectado, las imágenes se redimensionan para tener un área total de píxeles cercana a 1024x1024 antes de la codificación.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | La salida de acondicionamiento final, que contiene el *prompt* de texto codificado y puede incluir *embeddings* de imágenes codificadas y/o latentes de referencia si se proporcionaron imágenes. |
