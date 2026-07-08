> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/CreateList/pt-BR.md)

O nó Create List combina múltiplas entradas em uma única lista sequencial. Ele recebe qualquer número de entradas do mesmo tipo de dados e as concatena na ordem em que são conectadas. Este nó é útil para preparar lotes de dados, como imagens ou texto, para serem processados por outros nós em um fluxo de trabalho.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `input_*` | Varia | Sim | Qualquer | Um número variável de slots de entrada. Você pode adicionar mais entradas clicando no ícone de mais (+). Todas as entradas devem ser do mesmo tipo de dados (por exemplo, todas IMAGE ou todas STRING). |

**Observação:** O nó criará automaticamente novos slots de entrada conforme você conecta itens. Todas as entradas conectadas devem compartilhar o mesmo tipo de dados para que o nó funcione corretamente.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `list` | Varia | Uma única lista contendo todos os itens das entradas conectadas, concatenados na ordem em que foram fornecidos. O tipo de dados da saída corresponde ao tipo de dados da entrada. |
