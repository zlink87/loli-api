> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerCreativeNode/es.md)

Este nodo utiliza el servicio Magnific AI para aumentar la escala y mejorar creativamente una imagen. Permite guiar la mejora con un texto descriptivo (prompt), elegir un estilo específico para optimizar el proceso y controlar varios aspectos creativos como el detalle, el parecido con la original y la fuerza de la estilización. El nodo genera una imagen de mayor resolución según el factor elegido (2x, 4x, 8x o 16x), con un tamaño máximo de salida de 25,3 megapíxeles.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Sí | - | La imagen de entrada que se va a escalar y mejorar. |
| `prompt` | STRING | No | - | Una descripción textual para guiar la mejora creativa de la imagen. Es opcional (valor por defecto: vacío). |
| `scale_factor` | COMBO | Sí | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | El factor por el cual se aumentarán las dimensiones de la imagen. |
| `optimized_for` | COMBO | Sí | `"standard"`<br>`"soft_portraits"`<br>`"hard_portraits"`<br>`"art_n_illustration"`<br>`"videogame_assets"`<br>`"nature_n_landscapes"`<br>`"films_n_photography"`<br>`"3d_renders"`<br>`"science_fiction_n_horror"` | El estilo o tipo de contenido para el cual optimizar el proceso de mejora. |
| `creativity` | INT | No | -10 a 10 | Controla el nivel de interpretación creativa aplicada a la imagen (valor por defecto: 0). |
| `hdr` | INT | No | -10 a 10 | El nivel de definición y detalle (valor por defecto: 0). |
| `resemblance` | INT | No | -10 a 10 | El nivel de parecido con la imagen original (valor por defecto: 0). |
| `fractality` | INT | No | -10 a 10 | La fuerza del prompt y la complejidad por píxel cuadrado (valor por defecto: 0). |
| `engine` | COMBO | Sí | `"automatic"`<br>`"magnific_illusio"`<br>`"magnific_sharpy"`<br>`"magnific_sparkle"` | El motor de IA específico a utilizar para el procesamiento. |
| `auto_downscale` | BOOLEAN | No | - | Cuando está habilitado, el nodo reducirá automáticamente la escala de la imagen de entrada si el aumento solicitado excediera el tamaño máximo de salida permitido de 25,3 megapíxeles (valor por defecto: Falso). |

**Restricciones:**

* La entrada `image` debe ser exactamente una imagen.
* La imagen de entrada debe tener una altura y un ancho mínimos de 160 píxeles.
* La relación de aspecto de la imagen de entrada debe estar entre 1:3 y 3:1.
* El tamaño final de salida (dimensiones de entrada multiplicadas por el `scale_factor`) no puede exceder los 25.300.000 píxeles. Si `auto_downscale` está deshabilitado y se excedería este límite, el nodo generará un error.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen de salida, mejorada creativamente y con mayor resolución. |
