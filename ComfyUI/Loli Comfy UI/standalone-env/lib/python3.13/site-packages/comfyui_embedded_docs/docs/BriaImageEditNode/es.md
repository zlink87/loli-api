> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/BriaImageEditNode/es.md)

El nodo Bria FIBO Image Edit permite modificar una imagen existente mediante una instrucción de texto. Envía la imagen y su indicación (prompt) a la API de Bria, que utiliza el modelo FIBO para generar una nueva versión editada de la imagen según su solicitud. También puede proporcionar una máscara para limitar las ediciones a un área específica.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sí | `"FIBO"` | La versión del modelo a utilizar para la edición de imágenes. |
| `image` | IMAGE | Sí | - | La imagen de entrada que desea editar. |
| `prompt` | STRING | No | - | La instrucción de texto que describe cómo editar la imagen (valor por defecto: vacío). |
| `negative_prompt` | STRING | No | - | Texto que describe lo que no desea que aparezca en la imagen editada (valor por defecto: vacío). |
| `structured_prompt` | STRING | No | - | Una cadena que contiene la indicación de edición estructurada en formato JSON. Utilice esta opción en lugar del `prompt` habitual para un control preciso y programático (valor por defecto: vacío). |
| `seed` | INT | Sí | 1 a 2147483647 | Un número utilizado para inicializar la generación aleatoria, asegurando resultados reproducibles (valor por defecto: 1). |
| `guidance_scale` | FLOAT | Sí | 3.0 a 5.0 | Controla cuán estrechamente la imagen generada sigue la indicación. Un valor más alto resulta en una mayor adherencia (valor por defecto: 3.0). |
| `steps` | INT | Sí | 20 a 50 | El número de pasos de eliminación de ruido que realizará el modelo (valor por defecto: 50). |
| `moderation` | DYNAMICCOMBO | Sí | `"true"`<br>`"false"` | Habilita o deshabilita la moderación de contenido. Seleccionar `"true"` revela opciones de moderación adicionales. |
| `mask` | MASK | No | - | Una imagen de máscara opcional. Si se proporciona, las ediciones solo se aplicarán a las áreas enmascaradas de la imagen. |

**Restricciones importantes:**

* Debe proporcionar al menos una de las entradas `prompt` o `structured_prompt`. Ambas no pueden estar vacías.
* Se requiere exactamente una entrada `image`.
* Cuando el parámetro `moderation` se establece en `"true"`, se habilitan tres entradas booleanas adicionales: `prompt_content_moderation`, `visual_input_moderation` y `visual_output_moderation`.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `IMAGE` | IMAGE | La imagen editada devuelta por la API de Bria. |
| `structured_prompt` | STRING | La indicación estructurada que se utilizó o generó durante el proceso de edición. |
