> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2TextToVideoNode/pt-BR.md)

O nó Vidu2 Text-to-Video Generation cria um vídeo a partir de uma descrição textual. Ele se conecta a uma API externa para gerar conteúdo de vídeo com base no seu prompt, permitindo que você controle a duração, o estilo visual e o formato do vídeo.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"viduq2"` | O modelo de IA a ser usado para a geração de vídeo. Atualmente, apenas um modelo está disponível. |
| `prompt` | STRING | Sim | - | Uma descrição textual para a geração do vídeo, com um comprimento máximo de 2000 caracteres. |
| `duration` | INT | Não | 1 a 10 | A duração do vídeo gerado em segundos. O valor pode ser ajustado usando um controle deslizante (padrão: 5). |
| `seed` | INT | Não | 0 a 2147483647 | Um número usado para controlar a aleatoriedade da geração, permitindo resultados reproduzíveis. Pode ser controlado após a geração (padrão: 1). |
| `aspect_ratio` | COMBO | Não | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | A relação proporcional entre a largura e a altura do vídeo. |
| `resolution` | COMBO | Não | `"720p"`<br>`"1080p"` | As dimensões em pixels do vídeo gerado. |
| `background_music` | BOOLEAN | Não | - | Se deve adicionar música de fundo ao vídeo gerado (padrão: Falso). |

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `output` | VIDEO | O arquivo de vídeo gerado. |
