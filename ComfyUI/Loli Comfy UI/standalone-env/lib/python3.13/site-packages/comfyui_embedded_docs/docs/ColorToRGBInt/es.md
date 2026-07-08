> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ColorToRGBInt/es.md)

El nodo ColorToRGBInt convierte un color especificado en formato hexadecimal en un valor entero único. Toma una cadena de color como `#FF5733` y calcula el entero RGB correspondiente combinando los componentes rojo, verde y azul.

## Entradas

| Parámetro | Tipo de Dato | Requerido | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `color` | STRING | Sí | N/A | Un valor de color en formato hexadecimal `#RRGGBB`. |

**Nota:** La cadena de entrada `color` debe tener exactamente 7 caracteres de longitud y comenzar con el símbolo `#`, seguido de seis dígitos hexadecimales (por ejemplo, `#FF0000` para rojo). El nodo generará un error si el formato es incorrecto.

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `rgb_int` | INT | El valor entero RGB calculado. Se deriva de la fórmula: `(Rojo * 65536) + (Verde * 256) + Azul`. |
