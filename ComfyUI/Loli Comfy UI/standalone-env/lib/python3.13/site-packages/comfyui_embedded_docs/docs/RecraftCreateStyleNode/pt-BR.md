> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/RecraftCreateStyleNode/pt-BR.md)

Este nó cria um estilo personalizado para geração de imagens através do upload de imagens de referência. Você pode fazer upload de 1 a 5 imagens para definir o novo estilo, e o nó retornará um ID de estilo único que pode ser usado com outros nós da Recraft. O tamanho total combinado de todos os arquivos de imagem enviados não deve exceder 5 MB.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `style` | STRING | Sim | `"realistic_image"`<br>`"digital_illustration"` | O estilo base das imagens geradas. |
| `images` | IMAGE | Sim | 1 a 5 imagens | Um conjunto de 1 a 5 imagens de referência usadas para criar o estilo personalizado. |

**Observação:** O tamanho total de arquivo de todas as imagens na entrada `images` deve ser inferior a 5 MB. O nó falhará se este limite for excedido.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `style_id` | STRING | O identificador único para o novo estilo personalizado criado. |
