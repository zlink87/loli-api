> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ImageToVideoNode/pt-BR.md)

O nó Geração de Vídeo Vidu2 a partir de Imagem cria uma sequência de vídeo a partir de uma única imagem de entrada. Ele utiliza um modelo Vidu2 especificado para animar a cena com base em um prompt de texto opcional, controlando a duração, a resolução e a intensidade do movimento do vídeo.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | O modelo Vidu2 a ser usado para a geração do vídeo. Diferentes modelos oferecem compensações variadas entre velocidade e qualidade. |
| `image` | IMAGE | Sim | - | Uma imagem a ser usada como o quadro inicial do vídeo gerado. Apenas uma imagem é permitida. |
| `prompt` | STRING | Não | - | Um prompt de texto opcional para a geração do vídeo (máximo de 2000 caracteres). O padrão é uma string vazia. |
| `duration` | INT | Sim | 1 a 10 | A duração do vídeo gerado em segundos. O padrão é 5. |
| `seed` | INT | Não | 0 a 2147483647 | Um valor de semente para a geração de números aleatórios, para garantir resultados reproduzíveis. O padrão é 1. |
| `resolution` | COMBO | Sim | `"720p"`<br>`"1080p"` | A resolução de saída do vídeo gerado. |
| `movement_amplitude` | COMBO | Sim | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | A amplitude de movimento dos objetos no quadro. |

**Restrições:**

* A entrada `image` deve conter exatamente uma imagem.
* A proporção da imagem de entrada deve estar entre 1:4 e 4:1.
* O texto do `prompt` está limitado a um máximo de 2000 caracteres.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `output` | VIDEO | O arquivo de vídeo gerado. |
