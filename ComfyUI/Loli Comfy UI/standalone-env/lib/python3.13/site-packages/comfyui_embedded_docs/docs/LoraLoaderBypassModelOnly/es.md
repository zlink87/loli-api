> Esta documentación fue generada por IA. Si encuentra algún error o tiene sugerencias de mejora, ¡no dude en contribuir! [Editar en GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypassModelOnly/es.md)

Este nodo aplica un LoRA (Adaptación de Bajo Rango) a un modelo para modificar su comportamiento, pero solo afecta al componente del modelo en sí. Carga un archivo LoRA específico y ajusta los pesos del modelo con una intensidad dada, dejando sin cambios otros componentes como el codificador de texto CLIP.

## Entradas

| Parámetro | Tipo de Dato | Obligatorio | Rango | Descripción |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Sí | - | El modelo base al que se aplicarán los ajustes del LoRA. |
| `lora_name` | STRING | Sí | (Lista de archivos LoRA disponibles) | El nombre del archivo LoRA a cargar y aplicar. Las opciones se completan con los archivos del directorio `loras`. |
| `strength_model` | FLOAT | Sí | -100.0 a 100.0 | La intensidad del efecto del LoRA sobre los pesos del modelo. Un valor positivo aplica el LoRA, un valor negativo aplica el inverso, y un valor de 0 no tiene efecto (por defecto: 1.0). |

## Salidas

| Nombre de Salida | Tipo de Dato | Descripción |
|-------------|-----------|-------------|
| `model` | MODEL | El modelo modificado con los ajustes del LoRA aplicados a sus pesos. |
