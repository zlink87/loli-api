> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextToModelNode/pt-BR.md)

O nó Meshy: Texto para Modelo utiliza a API Meshy para gerar um modelo 3D a partir de uma descrição textual. Ele envia uma solicitação à API com seu prompt e configurações, aguarda a conclusão da geração e faz o download dos arquivos do modelo resultante.

## Entradas

| Parâmetro | Tipo de Dado | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"latest"` | Especifica a versão do modelo de IA a ser usada. Atualmente, apenas a versão "latest" está disponível. |
| `prompt` | STRING | Sim | - | A descrição textual do modelo 3D que você deseja gerar. Deve ter entre 1 e 600 caracteres. |
| `style` | COMBO | Sim | `"realistic"`<br>`"sculpture"` | O estilo artístico para o modelo 3D gerado. |
| `should_remesh` | DYNAMIC COMBO | Sim | `"true"`<br>`"false"` | Controla se a malha gerada é processada. Quando definido como "false", o nó retorna uma malha triangular não processada. Selecionar "true" revela parâmetros adicionais para topologia e contagem de polígonos. |
| `topology` | COMBO | Não* | `"triangle"`<br>`"quad"` | O tipo de polígono alvo para o modelo retopologizado. Este parâmetro só está disponível e é obrigatório quando `should_remesh` está definido como "true". |
| `target_polycount` | INT | Não* | 100 - 300000 | O número alvo de polígonos para o modelo retopologizado. O padrão é 300000. Este parâmetro só está disponível e é obrigatório quando `should_remesh` está definido como "true". |
| `symmetry_mode` | COMBO | Sim | `"auto"`<br>`"on"`<br>`"off"` | Controla a simetria no modelo gerado. |
| `pose_mode` | COMBO | Sim | `""`<br>`"A-pose"`<br>`"T-pose"` | Especifica o modo de pose para o modelo gerado. Uma string vazia significa que nenhuma pose específica é solicitada. |
| `seed` | INT | Sim | 0 - 2147483647 | Um valor de semente para a geração. Definir isso controla se o nó deve ser executado novamente, mas os resultados são não determinísticos independentemente do valor da semente. O padrão é 0. |

*Nota: Os parâmetros `topology` e `target_polycount` são condicionalmente obrigatórios. Eles só aparecem e devem ser definidos quando o parâmetro `should_remesh` está definido como "true".

## Saídas

| Nome da Saída | Tipo de Dado | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | O nome do arquivo do modelo GLB gerado. Esta saída é fornecida para compatibilidade com versões anteriores. |
| `meshy_task_id` | MESHY_TASK_ID | O identificador único para a tarefa da API Meshy. |
| `GLB` | FILE3DGLB | O arquivo do modelo 3D gerado no formato GLB. |
| `FBX` | FILE3DFBX | O arquivo do modelo 3D gerado no formato FBX. |
