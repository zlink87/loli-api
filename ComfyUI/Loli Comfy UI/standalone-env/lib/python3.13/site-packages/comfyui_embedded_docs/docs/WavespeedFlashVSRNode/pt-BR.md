> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedFlashVSRNode/pt-BR.md)

O WavespeedFlashVSRNode é um upscaler de vídeo rápido e de alta qualidade que aumenta a resolução e restaura a nitidez de filmagens de baixa resolução ou desfocadas. Ele processa um vídeo de entrada e gera um novo vídeo em uma resolução mais alta selecionada pelo usuário.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `video` | VIDEO | Sim | N/A | O arquivo de vídeo de entrada a ser upscaled. |
| `target_resolution` | STRING | Sim | `"720p"`<br>`"1080p"`<br>`"2K"`<br>`"4K"` | A resolução desejada para o vídeo de saída upscaled. |

**Restrições de Entrada:**

* O arquivo de entrada `video` deve estar no formato de contêiner MP4.
* A duração do `video` de entrada deve estar entre 5 segundos e 10 minutos (600 segundos).

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `output` | VIDEO | O arquivo de vídeo upscaled na resolução alvo selecionada. |
