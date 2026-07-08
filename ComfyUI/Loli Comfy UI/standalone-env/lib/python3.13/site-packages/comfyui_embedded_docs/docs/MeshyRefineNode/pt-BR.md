> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/pt-BR.md)

O nó Meshy: Refine Draft Model recebe um modelo 3D rascunho previamente gerado e melhora sua qualidade, adicionando texturas opcionalmente. Ele submete uma tarefa de refinamento à API da Meshy e retorna os arquivos finais do modelo 3D após a conclusão do processamento.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"latest"` | Especifica o modelo de IA a ser usado para o refinamento. Atualmente, apenas o modelo "latest" está disponível. |
| `meshy_task_id` | MESHY_TASK_ID | Sim | - | O ID de tarefa único do modelo rascunho que você deseja refinar. |
| `enable_pbr` | BOOLEAN | Não | - | Gera mapas PBR (metálico, rugosidade, normal) além da cor base. Nota: isso deve ser definido como falso ao usar o estilo Sculpture, pois o estilo Sculpture gera seu próprio conjunto de mapas PBR. (padrão: `False`) |
| `texture_prompt` | STRING | Não | - | Fornece um prompt de texto para orientar o processo de texturização. Máximo de 600 caracteres. Não pode ser usado ao mesmo tempo que 'texture_image'. (padrão: string vazia) |
| `texture_image` | IMAGE | Não | - | Apenas um dos parâmetros 'texture_image' ou 'texture_prompt' pode ser usado ao mesmo tempo. (opcional) |

**Nota:** As entradas `texture_prompt` e `texture_image` são mutuamente exclusivas. Você não pode fornecer um prompt de texto e uma imagem para texturização na mesma operação.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | O nome do arquivo do modelo GLB gerado. (Apenas para compatibilidade com versões anteriores) |
| `meshy_task_id` | MESHY_TASK_ID | O ID de tarefa único para o trabalho de refinamento submetido. |
| `GLB` | FILE3DGLB | O modelo 3D refinado final no formato GLB. |
| `FBX` | FILE3DFBX | O modelo 3D refinado final no formato FBX. |
