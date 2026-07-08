> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3ImageToVideoNode/pt-BR.md)

O nó Geração de Vídeo a partir de Imagem Vidu Q3 cria uma sequência de vídeo a partir de uma imagem de entrada. Ele utiliza o modelo Vidu Q3 Pro para animar a imagem, opcionalmente guiado por um prompt de texto, e gera um arquivo de vídeo.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"viduq3-pro"` | Modelo a ser usado para a geração do vídeo. |
| `model.resolution` | COMBO | Sim | `"720p"`<br>`"1080p"`<br>`"2K"` | Resolução do vídeo de saída. |
| `model.duration` | INT | Sim | 1 a 16 | Duração do vídeo de saída em segundos (padrão: 5). |
| `model.audio` | BOOLEAN | Sim | `True` / `False` | Quando habilitado, gera vídeo com som (incluindo diálogos e efeitos sonoros) (padrão: False). |
| `image` | IMAGE | Sim | - | Uma imagem a ser usada como o quadro inicial do vídeo gerado. |
| `prompt` | STRING | Não | - | Um prompt de texto opcional para a geração do vídeo (máximo de 2000 caracteres) (padrão: vazio). |
| `seed` | INT | Não | 0 a 2147483647 | Um valor de semente para controlar a aleatoriedade da geração (padrão: 1). |

**Observação:** A `image` deve ter uma proporção de aspecto entre 1:4 e 4:1 (retrato a paisagem). O `prompt` é opcional, mas não pode exceder 2000 caracteres.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `output` | VIDEO | O arquivo de vídeo gerado. |
