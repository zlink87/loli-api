> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageEditNode/pt-BR.md)

O nó Grok Image Edit modifica uma imagem existente com base em um prompt de texto. Ele usa a API Grok para gerar uma ou mais novas imagens que são variações da entrada, orientadas pela sua descrição.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"grok-imagine-image-beta"` | O modelo de IA específico a ser usado para a edição de imagem. |
| `image` | IMAGE | Sim | | A imagem de entrada a ser editada. Apenas uma imagem é suportada. |
| `prompt` | STRING | Sim | | O prompt de texto usado para gerar a imagem editada. |
| `resolution` | COMBO | Sim | `"1K"` | A resolução para a imagem de saída. |
| `number_of_images` | INT | Não | 1 a 10 | Número de imagens editadas a serem geradas (padrão: 1). |
| `seed` | INT | Não | 0 a 2147483647 | Semente para determinar se o nó deve ser executado novamente; os resultados reais são não determinísticos independentemente da semente (padrão: 0). |

**Observação:** A entrada `image` deve conter exatamente uma imagem. Fornecer múltiplas imagens causará um erro.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `output` | IMAGE | A(s) imagem(ns) editada(s) gerada(s) pelo nó. Se `number_of_images` for maior que 1, as saídas são concatenadas em um lote. |
