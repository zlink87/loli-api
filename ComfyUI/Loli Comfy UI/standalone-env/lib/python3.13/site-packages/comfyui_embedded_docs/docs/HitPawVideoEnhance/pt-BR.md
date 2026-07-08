> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawVideoEnhance/pt-BR.md)

O nó HitPaw Video Enhance utiliza uma API externa para melhorar a qualidade de vídeos. Ele aumenta a escala de vídeos de baixa resolução para uma resolução mais alta, remove artefatos visuais e reduz ruído. O custo do processamento é calculado por segundo do vídeo de entrada.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | DYNAMIC COMBO | Sim | Múltiplas opções disponíveis | O modelo de IA a ser usado para o aprimoramento do vídeo. Selecionar um modelo revela um parâmetro aninhado `resolution`. |
| `model.resolution` | COMBO | Sim | `"original"`<br>`"720p"`<br>`"1080p"`<br>`"2k/qhd"`<br>`"4k/uhd"`<br>`"8k"` | A resolução de destino para o vídeo aprimorado. Algumas opções podem estar indisponíveis dependendo do `model` selecionado. |
| `video` | VIDEO | Sim | N/A | O arquivo de vídeo de entrada a ser aprimorado. |

**Restrições:**

* O `video` de entrada deve ter uma duração entre 0,5 segundos e 60 minutos (3600 segundos).
* A `resolution` selecionada deve ser maior que as dimensões do vídeo de entrada. Se o vídeo for quadrado, a resolução selecionada deve ser maior que sua largura/altura. Para vídeos não quadrados, a resolução selecionada deve ser maior que a dimensão mais curta do vídeo. Se a resolução de destino for menor, um erro será gerado. Escolha `"original"` para manter a resolução do vídeo de entrada.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `video` | VIDEO | O arquivo de vídeo aprimorado. |
