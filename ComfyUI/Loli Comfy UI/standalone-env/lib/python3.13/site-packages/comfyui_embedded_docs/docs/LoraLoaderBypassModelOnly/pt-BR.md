> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypassModelOnly/pt-BR.md)

Este nó aplica um LoRA (Adaptação de Baixa Classificação) a um modelo para modificar seu comportamento, mas afeta apenas o componente do modelo em si. Ele carrega um arquivo LoRA especificado e ajusta os pesos do modelo por uma determinada intensidade, deixando outros componentes como o codificador de texto CLIP inalterados.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|---------------|-------------|-----------|-----------|
| `model` | MODEL | Sim | - | O modelo base ao qual os ajustes do LoRA serão aplicados. |
| `lora_name` | STRING | Sim | (Lista de arquivos LoRA disponíveis) | O nome do arquivo LoRA a ser carregado e aplicado. As opções são preenchidas a partir dos arquivos no diretório `loras`. |
| `strength_model` | FLOAT | Sim | -100.0 a 100.0 | A intensidade do efeito do LoRA nos pesos do modelo. Um valor positivo aplica o LoRA, um valor negativo aplica o inverso e um valor de 0 não tem efeito (padrão: 1.0). |

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|---------------|---------------|-----------|
| `model` | MODEL | O modelo modificado com os ajustes do LoRA aplicados aos seus pesos. |
