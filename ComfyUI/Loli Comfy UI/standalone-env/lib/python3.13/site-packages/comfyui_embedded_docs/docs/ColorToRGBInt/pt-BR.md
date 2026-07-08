> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ColorToRGBInt/pt-BR.md)

O nó ColorToRGBInt converte uma cor especificada em formato hexadecimal em um único valor inteiro. Ele recebe uma string de cor como `#FF5733` e calcula o inteiro RGB correspondente combinando os componentes vermelho, verde e azul.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `color` | STRING | Sim | N/A | Um valor de cor no formato hexadecimal `#RRGGBB`. |

**Observação:** A string de entrada `color` deve ter exatamente 7 caracteres e começar com o símbolo `#`, seguido por seis dígitos hexadecimais (por exemplo, `#FF0000` para vermelho). O nó gerará um erro se o formato estiver incorreto.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `rgb_int` | INT | O valor inteiro RGB calculado. Ele é derivado da fórmula: `(Vermelho * 65536) + (Verde * 256) + Azul`. |
