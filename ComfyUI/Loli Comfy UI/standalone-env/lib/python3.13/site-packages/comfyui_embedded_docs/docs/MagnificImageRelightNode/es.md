> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageRelightNode/es.md)

El nodo Magnific Image Relight ajusta la iluminación de una imagen de entrada. Puede aplicar iluminación estilística basada en un texto descriptivo (prompt) o transferir las características de iluminación de una imagen de referencia opcional. El nodo ofrece varios controles para afinar el brillo, el contraste y el estado de ánimo general de la salida final.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Sí | N/A | La imagen a la que se le ajustará la iluminación. Se requiere exactamente una imagen. Las dimensiones mínimas son 160x160 píxeles. La relación de aspecto debe estar entre 1:3 y 3:1. |
| `prompt` | STRING | No | N/A | Guía descriptiva para la iluminación. Admite notación de énfasis (1-1.4). Por defecto es una cadena vacía. |
| `light_transfer_strength` | INT | Sí | 0 a 100 | Intensidad de aplicación de la transferencia de luz. Por defecto: 100. |
| `style` | COMBO | Sí | `"standard"`<br>`"darker_but_realistic"`<br>`"clean"`<br>`"smooth"`<br>`"brighter"`<br>`"contrasted_n_hdr"`<br>`"just_composition"` | Preferencia de estilo para la salida. |
| `interpolate_from_original` | BOOLEAN | Sí | N/A | Restringe la libertad de generación para que coincida más estrechamente con el original. Por defecto: Falso. |
| `change_background` | BOOLEAN | Sí | N/A | Modifica el fondo basándose en el prompt o la referencia. Por defecto: Verdadero. |
| `preserve_details` | BOOLEAN | Sí | N/A | Mantiene la textura y los detalles finos del original. Por defecto: Verdadero. |
| `advanced_settings` | DYNAMICCOMBO | Sí | `"disabled"`<br>`"enabled"` | Opciones de ajuste fino para un control avanzado de la iluminación. Cuando se establece en `"enabled"`, se activan parámetros adicionales. |
| `reference_image` | IMAGE | No | N/A | Imagen de referencia opcional de la cual transferir la iluminación. Si se proporciona, se requiere exactamente una imagen. Las dimensiones mínimas son 160x160 píxeles. La relación de aspecto debe estar entre 1:3 y 3:1. |

**Nota sobre Ajustes Avanzados:** Cuando `advanced_settings` se establece en `"enabled"`, los siguientes parámetros anidados se activan:

* `whites`: Ajusta los tonos más brillantes de la imagen. Rango: 0 a 100. Por defecto: 50.
* `blacks`: Ajusta los tonos más oscuros de la imagen. Rango: 0 a 100. Por defecto: 50.
* `brightness`: Ajuste del brillo general. Rango: 0 a 100. Por defecto: 50.
* `contrast`: Ajuste del contraste. Rango: 0 a 100. Por defecto: 50.
* `saturation`: Ajuste de la saturación del color. Rango: 0 a 100. Por defecto: 50.
* `engine`: Selección del motor de procesamiento. Opciones: `"automatic"`, `"balanced"`, `"cool"`, `"real"`, `"illusio"`, `"fairy"`, `"colorful_anime"`, `"hard_transform"`, `"softy"`.
* `transfer_light_a`: La intensidad de la transferencia de luz. Opciones: `"automatic"`, `"low"`, `"medium"`, `"normal"`, `"high"`, `"high_on_faces"`.
* `transfer_light_b`: También modifica la intensidad de la transferencia de luz. Puede combinarse con el control anterior para efectos variados. Opciones: `"automatic"`, `"composition"`, `"straight"`, `"smooth_in"`, `"smooth_out"`, `"smooth_both"`, `"reverse_both"`, `"soft_in"`, `"soft_out"`, `"soft_mid"`, `"style_shift"`, `"strong_shift"`.
* `fixed_generation`: Garantiza una salida consistente con la misma configuración. Por defecto: Verdadero.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen con la iluminación ajustada. |
