> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/EmptyAceStep1.5LatentAudio/pt-BR.md)

O nó Empty Ace Step 1.5 Latent Audio cria um tensor latente vazio projetado para processamento de áudio. Ele gera um latente de áudio silencioso de uma duração e tamanho de lote especificados, que pode ser usado como ponto de partida para fluxos de trabalho de geração de áudio no ComfyUI. O nó calcula o comprimento latente com base nos segundos de entrada e em uma taxa de amostragem fixa.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `seconds` | FLOAT | Não | 1.0 - 1000.0 | A duração do áudio a ser gerado, em segundos (padrão: 120.0). |
| `batch_size` | INT | Não | 1 - 4096 | O número de imagens latentes no lote (padrão: 1). |

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `LATENT` | LATENT | Um tensor latente vazio representando áudio silencioso, com um identificador de tipo "audio". |
