> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/BriaImageEditNode/pt-BR.md)

O nó Bria FIBO Image Edit permite que você modifique uma imagem existente usando uma instrução textual. Ele envia a imagem e seu prompt para a API da Bria, que usa o modelo FIBO para gerar uma nova versão editada da imagem com base na sua solicitação. Você também pode fornecer uma máscara para limitar as edições a uma área específica.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"FIBO"` | A versão do modelo a ser usada para edição de imagem. |
| `image` | IMAGE | Sim | - | A imagem de entrada que você deseja editar. |
| `prompt` | STRING | Não | - | A instrução textual descrevendo como editar a imagem (padrão: vazio). |
| `negative_prompt` | STRING | Não | - | Texto descrevendo o que você não quer que apareça na imagem editada (padrão: vazio). |
| `structured_prompt` | STRING | Não | - | Uma string contendo o prompt de edição estruturado no formato JSON. Use isso em vez do prompt usual para um controle preciso e programático (padrão: vazio). |
| `seed` | INT | Sim | 1 a 2147483647 | Um número usado para inicializar a geração aleatória, garantindo resultados reproduzíveis (padrão: 1). |
| `guidance_scale` | FLOAT | Sim | 3.0 a 5.0 | Controla o quanto a imagem gerada segue o prompt. Um valor maior resulta em uma aderência mais forte (padrão: 3.0). |
| `steps` | INT | Sim | 20 a 50 | O número de etapas de remoção de ruído que o modelo realizará (padrão: 50). |
| `moderation` | DYNAMICCOMBO | Sim | `"true"`<br>`"false"` | Habilita ou desabilita a moderação de conteúdo. Selecionar `"true"` revela opções adicionais de moderação. |
| `mask` | MASK | Não | - | Uma imagem de máscara opcional. Se fornecida, as edições serão aplicadas apenas às áreas mascaradas da imagem. |

**Restrições Importantes:**

* Você deve fornecer pelo menos uma das entradas `prompt` ou `structured_prompt`. Ambas não podem estar vazias.
* Exatamente uma entrada `image` é obrigatória.
* Quando o parâmetro `moderation` é definido como `"true"`, três entradas booleanas adicionais ficam disponíveis: `prompt_content_moderation`, `visual_input_moderation` e `visual_output_moderation`.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `IMAGE` | IMAGE | A imagem editada retornada pela API da Bria. |
| `structured_prompt` | STRING | O prompt estruturado que foi usado ou gerado durante o processo de edição. |
