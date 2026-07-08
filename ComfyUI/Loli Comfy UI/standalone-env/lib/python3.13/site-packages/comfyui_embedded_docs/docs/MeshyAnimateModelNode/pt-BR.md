> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyAnimateModelNode/pt-BR.md)

Este nó aplica uma animação específica a um modelo de personagem 3D que já foi rigado usando o serviço Meshy. Ele recebe um ID de tarefa de uma operação de rigging anterior e um ID de ação para selecionar a animação desejada da biblioteca. O nó então processa a solicitação e retorna o modelo animado nos formatos de arquivo GLB e FBX.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `rig_task_id` | STRING | Sim | N/A | O ID de tarefa único de uma operação de rigging de personagem Meshy previamente concluída. |
| `action_id` | INT | Sim | 0 a 696 | O número de ID da ação de animação a ser aplicada. Visite <https://docs.meshy.ai/en/api/animation-library> para uma lista de valores disponíveis. (padrão: 0) |

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | Um identificador de string para o modelo animado. Esta saída é fornecida apenas para compatibilidade com versões anteriores. |
| `GLB` | FILE3DGLB | O arquivo do modelo 3D animado no formato GLB. |
| `FBX` | FILE3DFBX | O arquivo do modelo 3D animado no formato FBX. |
