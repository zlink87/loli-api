> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ReferenceTimbreAudio/pt-BR.md)

Este nó define um timbre de áudio de referência para uso no processo "ace step 1.5". Ele funciona recebendo uma entrada de condicionamento e, opcionalmente, uma representação latente de áudio, e então anexa esses dados latentes ao condicionamento para uso por nós subsequentes no fluxo de trabalho.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `conditioning` | CONDITIONING | Sim | | Os dados de condicionamento aos quais as informações de áudio de referência serão anexadas. |
| `latent` | LATENT | Não | | Uma representação latente opcional do áudio de referência. Quando fornecida, suas amostras são adicionadas ao condicionamento. |

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `conditioning` | CONDITIONING | Os dados de condicionamento modificados, agora contendo os latentes do timbre de áudio de referência, se a entrada opcional `latent` foi fornecida. |
