> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyImageToModelNode/pt-BR.md)

O nó Meshy: Image to Model utiliza a API Meshy para gerar um modelo 3D a partir de uma única imagem de entrada. Ele faz o upload da sua imagem, submete uma tarefa de processamento e retorna os arquivos do modelo 3D gerado (GLB e FBX) junto com o ID da tarefa para referência.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"latest"` | Especifica a versão do modelo de IA a ser usada para a geração. |
| `image` | IMAGE | Sim | - | A imagem de entrada a ser convertida em um modelo 3D. |
| `should_remesh` | DYNAMIC COMBO | Sim | `"true"`<br>`"false"` | Determina se a malha gerada deve ser processada. Quando definido como `"false"`, o nó retorna uma malha triangular não processada. |
| `topology` | COMBO | Não* | `"triangle"`<br>`"quad"` | A topologia de polígonos alvo para o modelo remalhado. Esta entrada está disponível e é obrigatória apenas quando `should_remesh` está definido como `"true"`. |
| `target_polycount` | INT | Não* | 100 - 300000 | O número alvo de polígonos para o modelo remalhado. Esta entrada está disponível e é obrigatória apenas quando `should_remesh` está definido como `"true"`. O valor padrão é 300000. |
| `symmetry_mode` | COMBO | Sim | `"auto"`<br>`"on"`<br>`"off"` | Controla a simetria aplicada ao modelo 3D gerado. |
| `should_texture` | DYNAMIC COMBO | Sim | `"true"`<br>`"false"` | Determina se as texturas são geradas para o modelo. Definir como `"false"` ignora a fase de texturização e retorna uma malha sem texturas. |
| `enable_pbr` | BOOLEAN | Não* | - | Quando `should_texture` é `"true"`, esta opção gera mapas PBR (metálico, rugosidade, normal) além da cor base. O valor padrão é `False`. |
| `texture_prompt` | STRING | Não* | - | Um prompt de texto para orientar o processo de texturização (máximo de 600 caracteres). Esta entrada está disponível apenas quando `should_texture` é `"true"`. Não pode ser usada ao mesmo tempo que `texture_image`. |
| `texture_image` | IMAGE | Não* | - | Uma imagem para orientar o processo de texturização. Esta entrada está disponível apenas quando `should_texture` é `"true"`. Não pode ser usada ao mesmo tempo que `texture_prompt`. |
| `pose_mode` | COMBO | Sim | `""`<br>`"A-pose"`<br>`"T-pose"` | Especifica o modo de pose para o modelo gerado. |
| `seed` | INT | Sim | 0 - 2147483647 | Um valor de seed para o processo de geração. Os resultados são não determinísticos independentemente do valor da seed. O valor padrão é 0. |

**Nota sobre Restrições de Parâmetros:**

* As entradas `topology` e `target_polycount` são obrigatórias apenas quando `should_remesh` está definido como `"true"`.
* As entradas `enable_pbr`, `texture_prompt` e `texture_image` estão disponíveis apenas quando `should_texture` está definido como `"true"`.
* Você não pode usar `texture_prompt` e `texture_image` ao mesmo tempo. Se ambos forem fornecidos quando `should_texture` for `"true"`, o nó gerará um erro.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | O nome do arquivo do modelo GLB gerado. (Mantido para compatibilidade com versões anteriores). |
| `meshy_task_id` | MESHY_TASK_ID | O identificador único da tarefa da API Meshy, que pode ser usado para referência ou solução de problemas. |
| `GLB` | FILE3DGLB | O modelo 3D gerado no formato de arquivo GLB. |
| `FBX` | FILE3DFBX | O modelo 3D gerado no formato de arquivo FBX. |
