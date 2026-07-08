> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageNode/pt-BR.md)

O nó Grok Image gera uma ou mais imagens com base em uma descrição textual usando o modelo de IA Grok. Ele envia seu prompt para um serviço externo e retorna as imagens geradas como tensores que podem ser usados em seu fluxo de trabalho.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"grok-imagine-image-beta"` | O modelo Grok específico a ser usado para a geração de imagem. |
| `prompt` | STRING | Sim | N/A | O prompt de texto usado para gerar a imagem. Esta descrição orienta a IA sobre o que criar. |
| `aspect_ratio` | COMBO | Sim | `"1:1"`<br>`"2:3"`<br>`"3:2"`<br>`"3:4"`<br>`"4:3"`<br>`"9:16"`<br>`"16:9"`<br>`"9:19.5"`<br>`"19.5:9"`<br>`"9:20"`<br>`"20:9"`<br>`"1:2"`<br>`"2:1"` | A proporção largura-altura desejada para a imagem gerada. |
| `number_of_images` | INT | Não | 1 a 10 | Número de imagens a serem geradas (padrão: 1). |
| `seed` | INT | Não | 0 a 2147483647 | Um valor de semente para determinar se o nó deve ser executado novamente. Os resultados reais da imagem são não determinísticos e variarão mesmo com a mesma semente (padrão: 0). |

**Observação:** O parâmetro `seed` é usado principalmente para controlar quando o nó é reexecutado dentro de um fluxo de trabalho. Devido à natureza do serviço de IA externo, as imagens geradas não serão reproduzíveis ou idênticas entre execuções, mesmo com uma semente idêntica.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `output` | IMAGE | A imagem gerada ou um lote de imagens. Se `number_of_images` for 1, um único tensor de imagem é retornado. Se for maior que 1, um lote de tensores de imagem é retornado. |
