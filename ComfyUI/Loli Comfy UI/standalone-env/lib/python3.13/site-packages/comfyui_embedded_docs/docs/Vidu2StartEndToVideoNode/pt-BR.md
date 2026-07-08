> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2StartEndToVideoNode/pt-BR.md)

Este nó gera um vídeo interpolando entre um quadro inicial e um quadro final fornecidos, guiado por um prompt de texto. Ele utiliza um modelo Vidu especificado para criar uma transição suave entre as duas imagens ao longo de uma duração definida.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | O modelo Vidu a ser usado para a geração do vídeo. |
| `first_frame` | IMAGE | Sim | - | A imagem inicial para a sequência de vídeo. Apenas uma única imagem é permitida. |
| `end_frame` | IMAGE | Sim | - | A imagem final para a sequência de vídeo. Apenas uma única imagem é permitida. |
| `prompt` | STRING | Sim | - | Uma descrição textual que guia a geração do vídeo (máximo de 2000 caracteres). |
| `duration` | INT | Não | 2 a 8 | A duração do vídeo gerado em segundos (padrão: 5). |
| `seed` | INT | Não | 0 a 2147483647 | Um número usado para inicializar a geração aleatória para resultados reproduzíveis (padrão: 1). |
| `resolution` | COMBO | Não | `"720p"`<br>`"1080p"` | A resolução de saída do vídeo gerado. |
| `movement_amplitude` | COMBO | Não | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | A amplitude de movimento dos objetos no quadro. |

**Observação:** As imagens `first_frame` e `end_frame` devem ter proporções de aspecto semelhantes. O nó validará se suas proporções de aspecto estão dentro de uma faixa relativa de 0,8 a 1,25.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `output` | VIDEO | O arquivo de vídeo gerado. |
