> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerCreativeNode/pt-BR.md)

Este nó utiliza o serviço Magnific AI para ampliar e aprimorar criativamente uma imagem. Ele permite que você oriente o aprimoramento com um prompt de texto, escolha um estilo específico para otimizar e controle vários aspectos do processo criativo, como detalhe, semelhança com o original e força da estilização. O nó gera uma imagem ampliada no fator escolhido (2x, 4x, 8x ou 16x), com um tamanho máximo de saída de 25,3 megapixels.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Sim | - | A imagem de entrada a ser ampliada e aprimorada. |
| `prompt` | STRING | Não | - | Uma descrição textual para orientar o aprimoramento criativo da imagem. É opcional (padrão: vazio). |
| `scale_factor` | COMBO | Sim | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | O fator pelo qual as dimensões da imagem serão ampliadas. |
| `optimized_for` | COMBO | Sim | `"standard"`<br>`"soft_portraits"`<br>`"hard_portraits"`<br>`"art_n_illustration"`<br>`"videogame_assets"`<br>`"nature_n_landscapes"`<br>`"films_n_photography"`<br>`"3d_renders"`<br>`"science_fiction_n_horror"` | O estilo ou tipo de conteúdo para o qual otimizar o processo de aprimoramento. |
| `creativity` | INT | Não | -10 a 10 | Controla o nível de interpretação criativa aplicada à imagem (padrão: 0). |
| `hdr` | INT | Não | -10 a 10 | O nível de definição e detalhe (padrão: 0). |
| `resemblance` | INT | Não | -10 a 10 | O nível de semelhança com a imagem original (padrão: 0). |
| `fractality` | INT | Não | -10 a 10 | A força do prompt e da complexidade por pixel quadrado (padrão: 0). |
| `engine` | COMBO | Sim | `"automatic"`<br>`"magnific_illusio"`<br>`"magnific_sharpy"`<br>`"magnific_sparkle"` | O mecanismo de IA específico a ser usado para o processamento. |
| `auto_downscale` | BOOLEAN | Não | - | Quando ativado, o nó reduzirá automaticamente a escala da imagem de entrada se a ampliação solicitada exceder o tamanho máximo permitido de saída de 25,3 megapixels (padrão: Falso). |

**Restrições:**

* A `image` de entrada deve ser exatamente uma imagem.
* A imagem de entrada deve ter uma altura e largura mínimas de 160 pixels.
* A proporção da imagem de entrada deve estar entre 1:3 e 3:1.
* O tamanho final de saída (dimensões de entrada multiplicadas pelo `scale_factor`) não pode exceder 25.300.000 pixels. Se `auto_downscale` estiver desativado e esse limite for excedido, o nó gerará um erro.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `image` | IMAGE | A imagem de saída aprimorada criativamente e ampliada. |
