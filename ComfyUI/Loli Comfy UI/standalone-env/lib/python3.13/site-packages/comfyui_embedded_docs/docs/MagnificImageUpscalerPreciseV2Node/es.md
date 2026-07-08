> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerPreciseV2Node/es.md)

## Entradas

| Parámetro | Tipo de Datos | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Sí | - | La imagen de entrada que se va a escalar. Se requiere exactamente una imagen. Las dimensiones mínimas son 160x160 píxeles. La relación de aspecto debe estar entre 1:3 y 3:1. |
| `scale_factor` | STRING | Sí | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | El multiplicador de escalado deseado. |
| `flavor` | STRING | Sí | `"sublime"`<br>`"photo"`<br>`"photo_denoiser"` | El estilo de procesamiento. "sublime" es para uso general, "photo" está optimizado para fotografías y "photo_denoiser" es para fotos con ruido. |
| `sharpen` | INT | No | 0 a 100 | Controla la intensidad del enfoque de la imagen para aumentar la definición y claridad de los bordes. Valores más altos producen un resultado más nítido. Por defecto: 7. |
| `smart_grain` | INT | No | 0 a 100 | Añade un grano o realce de textura inteligente para evitar que la imagen escalada parezca demasiado suave o artificial. Por defecto: 7. |
| `ultra_detail` | INT | No | 0 a 100 | Controla la cantidad de detalles finos, texturas y microdetalles añadidos durante el proceso de escalado. Por defecto: 30. |
| `auto_downscale` | BOOLEAN | No | - | Cuando está habilitado, el nodo reducirá automáticamente la escala de la imagen de entrada si las dimensiones de salida calculadas excedieran la resolución máxima permitida de 10060x10060 píxeles. Esto ayuda a prevenir errores pero puede afectar la calidad. Por defecto: Falso. |

**Nota:** Si `auto_downscale` está deshabilitado y el tamaño de salida solicitado (dimensiones de entrada × `scale_factor`) excede los 10060x10060 píxeles, el nodo generará un error.

## Salidas

| Nombre de Salida | Tipo de Datos | Descripción |
|-------------|-----------|-------------|
| `image` | IMAGE | La imagen escalada resultante. |
