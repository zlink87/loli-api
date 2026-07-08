> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/pt-BR.md)

Este nó utiliza a API Hunyuan3D Pro da Tencent para gerar um modelo 3D a partir de uma ou mais imagens de entrada. Ele processa as imagens, as envia para a API e retorna os arquivos do modelo 3D gerado nos formatos GLB e OBJ.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"3.0"`<br>`"3.1"` | A versão do modelo Hunyuan3D a ser utilizada. A opção LowPoly não está disponível para o modelo `3.1`. |
| `image` | IMAGE | Sim | - | A imagem de entrada principal usada para gerar o modelo 3D. |
| `image_left` | IMAGE | Não | - | Uma imagem opcional do lado esquerdo do objeto para geração multi-visão. |
| `image_right` | IMAGE | Não | - | Uma imagem opcional do lado direito do objeto para geração multi-visão. |
| `image_back` | IMAGE | Não | - | Uma imagem opcional do lado traseiro do objeto para geração multi-visão. |
| `face_count` | INT | Sim | 40000 - 1500000 | O número alvo de faces para o modelo 3D gerado (padrão: 500000). |
| `generate_type` | DYNAMICCOMBO | Sim | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | O tipo de modelo 3D a ser gerado. Selecionar uma opção revela parâmetros adicionais relacionados. |
| `generate_type.pbr` | BOOLEAN | Não | - | Habilita a geração de material PBR (Physically Based Rendering). Este parâmetro só fica visível quando `generate_type` está definido como "Normal" ou "LowPoly" (padrão: Falso). |
| `generate_type.polygon_type` | COMBO | Não | `"triangle"`<br>`"quadrilateral"` | O tipo de polígono a ser usado na malha. Este parâmetro só fica visível quando `generate_type` está definido como "LowPoly". |
| `seed` | INT | Sim | 0 - 2147483647 | Um valor de semente para o processo de geração. A semente controla se o nó deve ser executado novamente; os resultados não são determinísticos independentemente da semente (padrão: 0). |

**Observação:** Todas as imagens de entrada devem ter uma largura e altura mínimas de 128 pixels.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | Uma saída legada para compatibilidade com versões anteriores. |
| `GLB` | FILE3DGLB | O modelo 3D gerado no formato de arquivo GLB (Binary GL Transmission Format). |
| `OBJ` | FILE3DOBJ | O modelo 3D gerado no formato de arquivo OBJ (Wavefront). |
