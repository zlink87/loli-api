> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRigModelNode/pt-BR.md)

O nó Meshy: Rig Model recebe uma tarefa de modelo 3D do Meshy e gera um modelo de personagem com rig. Ele cria automaticamente um esqueleto para o modelo, permitindo que ele seja posado e animado. O nó gera o modelo com rig nos formatos de arquivo GLB e FBX.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `meshy_task_id` | STRING | Sim | N/A | O ID único da tarefa de uma operação anterior do Meshy (por exemplo, texto-para-3D ou imagem-para-3D) que gerou o modelo a ser rigado. |
| `height_meters` | FLOAT | Sim | 0.1 a 15.0 | A altura aproximada do modelo do personagem em metros. Isso auxilia na precisão de escala e rigging (padrão: 1.7). |
| `texture_image` | IMAGE | Não | N/A | A imagem de textura de cor base com UV-unwrapped do modelo. |

**Observação:** O processo de auto-rigging atualmente não é adequado para malhas sem textura, ativos não humanoides ou ativos humanoides com estrutura de membros e corpo pouco clara.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | Uma saída legada para compatibilidade com versões anteriores, contendo o nome do arquivo do modelo GLB. |
| `rig_task_id` | STRING | O ID único da tarefa para esta operação de rigging, que pode ser usado para referenciar o resultado. |
| `GLB` | FILE3DGLB | O modelo de personagem 3D com rig salvo no formato de arquivo GLB. |
| `FBX` | FILE3DFBX | O modelo de personagem 3D com rig salvo no formato de arquivo FBX. |
