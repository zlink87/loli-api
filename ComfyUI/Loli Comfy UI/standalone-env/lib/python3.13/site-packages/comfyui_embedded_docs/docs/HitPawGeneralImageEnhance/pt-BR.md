> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/pt-BR.md)

Este nó aprimora imagens de baixa resolução aumentando-as para super-resolução, removendo artefatos e ruídos. Ele utiliza uma API externa para processar a imagem e pode ajustar automaticamente o tamanho de entrada para permanecer dentro dos limites de processamento. O tamanho máximo permitido para a saída é de 4 megapixels.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Sim | `"generative_portrait"`<br>`"generative"` | O modelo de aprimoramento a ser utilizado. |
| `image` | IMAGE | Sim | - | A imagem de entrada a ser aprimorada. |
| `upscale_factor` | INT | Sim | `1`<br>`2`<br>`4` | O fator pelo qual as dimensões da imagem serão aumentadas. |
| `auto_downscale` | BOOLEAN | Não | - | Reduz automaticamente a escala da imagem de entrada se a saída exceder o limite. (padrão: `False`) |

**Observação:** O nó gerará um erro se o tamanho de saída calculado (altura de entrada × upscale_factor × largura de entrada × upscale_factor) exceder 4.000.000 de pixels (4MP) e `auto_downscale` estiver desativado. Quando `auto_downscale` está ativado, o nó tentará reduzir a escala da imagem de entrada para caber dentro do limite antes de aplicar o fator de aumento solicitado.

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `image` | IMAGE | A imagem de saída aprimorada e com escala aumentada. |
