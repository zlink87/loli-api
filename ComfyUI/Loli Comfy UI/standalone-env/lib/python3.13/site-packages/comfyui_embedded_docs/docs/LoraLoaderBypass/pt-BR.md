> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypass/pt-BR.md)

O nó LoraLoaderBypass aplica um LoRA (Low-Rank Adaptation) a um modelo de difusão e a um modelo CLIP em um modo especial de "bypass". Diferente de um carregador LoRA padrão, este método não modifica permanentemente os pesos do modelo base. Em vez disso, ele calcula a saída adicionando o efeito do LoRA à passagem direta normal do modelo, o que é útil para treinamento ou ao trabalhar com modelos que têm seus pesos descarregados.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Sim | - | O modelo de difusão ao qual o LoRA será aplicado. |
| `clip` | CLIP | Sim | - | O modelo CLIP ao qual o LoRA será aplicado. |
| `lora_name` | COMBO | Sim | *Lista de arquivos LoRA disponíveis* | O nome do arquivo LoRA a ser aplicado. As opções são carregadas da pasta `loras`. |
| `strength_model` | FLOAT | Sim | -100.0 a 100.0 | A intensidade com que modificar o modelo de difusão. Este valor pode ser negativo (padrão: 1.0). |
| `strength_clip` | FLOAT | Sim | -100.0 a 100.0 | A intensidade com que modificar o modelo CLIP. Este valor pode ser negativo (padrão: 1.0). |

**Observação:** Se tanto `strength_model` quanto `strength_clip` forem definidos como 0, o nó retornará as entradas originais, não modificadas, `model` e `clip`, sem processamento.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `MODEL` | MODEL | O modelo de difusão com o LoRA aplicado no modo bypass. |
| `CLIP` | CLIP | O modelo CLIP com o LoRA aplicado no modo bypass. |
