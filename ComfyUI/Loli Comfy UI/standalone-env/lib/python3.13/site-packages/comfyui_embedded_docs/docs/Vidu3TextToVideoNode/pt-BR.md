> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3TextToVideoNode/pt-BR.md)

O nó Vidu Q3 Text-to-Video Generation cria um vídeo a partir de uma descrição textual. Ele utiliza o modelo Vidu Q3 Pro para gerar conteúdo de vídeo com base no seu prompt, permitindo que você controle a duração, a resolução e a proporção de aspecto do vídeo.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"viduq3-pro"` | Modelo a ser usado para a geração de vídeo. Selecionar esta opção revela parâmetros de configuração adicionais para proporção de aspecto, resolução, duração e áudio. |
| `model.aspect_ratio` | COMBO | Sim* | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | A proporção de aspecto do vídeo de saída. Este parâmetro é revelado quando o `model` é selecionado. |
| `model.resolution` | COMBO | Sim* | `"720p"`<br>`"1080p"` | Resolução do vídeo de saída. Este parâmetro é revelado quando o `model` é selecionado. |
| `model.duration` | INT | Sim* | 1 a 16 | Duração do vídeo de saída em segundos (padrão: 5). Este parâmetro é revelado quando o `model` é selecionado. |
| `model.audio` | BOOLEAN | Sim* | Verdadeiro/Falso | Quando habilitado, gera vídeo com som (incluindo diálogo e efeitos sonoros) (padrão: Falso). Este parâmetro é revelado quando o `model` é selecionado. |
| `prompt` | STRING | Sim | N/A | Uma descrição textual para a geração do vídeo, com um comprimento máximo de 2000 caracteres. |
| `seed` | INT | Não | 0 a 2147483647 | Um valor de semente para controlar a aleatoriedade da geração (padrão: 1). |

*Nota: Os parâmetros `aspect_ratio`, `resolution`, `duration` e `audio` são obrigatórios uma vez que o `model` é selecionado, pois fazem parte de sua configuração.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `video` | VIDEO | O arquivo de vídeo gerado. |
