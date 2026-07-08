> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentTextToModelNode/pt-BR.md)

Este nó utiliza a API Hunyuan3D Pro da Tencent para gerar um modelo 3D a partir de uma descrição textual. Ele envia uma solicitação para criar uma tarefa de geração, consulta periodicamente o resultado e faz o download dos arquivos finais do modelo nos formatos GLB e OBJ.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Sim | `"3.0"`<br>`"3.1"` | A versão do modelo Hunyuan3D a ser utilizada. A opção LowPoly não está disponível para o modelo `3.1`. |
| `prompt` | STRING | Sim | - | A descrição textual do modelo 3D a ser gerado. Suporta até 1024 caracteres. |
| `face_count` | INT | Sim | 40000 - 1500000 | O número alvo de faces para o modelo 3D gerado. Padrão: 500000. |
| `generate_type` | DYNAMICCOMBO | Sim | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | O tipo de modelo 3D a ser gerado. As opções disponíveis e seus parâmetros associados são:<br>- **Normal**: Gera um modelo padrão. Inclui um parâmetro `pbr` (padrão: `False`).<br>- **LowPoly**: Gera um modelo de baixo polígono. Inclui os parâmetros `polygon_type` (`"triangle"` ou `"quadrilateral"`) e `pbr` (padrão: `False`).<br>- **Geometry**: Gera um modelo apenas de geometria. |
| `seed` | INT | Não | 0 - 2147483647 | Um valor de semente para a geração. Os resultados são não determinísticos independentemente da semente. Definir uma nova semente controla se o nó deve ser executado novamente. Padrão: 0. |

**Observação:** O parâmetro `generate_type` é dinâmico. Selecionar `"LowPoly"` revelará entradas adicionais para `polygon_type` e `pbr`. Selecionar `"Normal"` revelará uma entrada para `pbr`. Selecionar `"Geometry"` não revelará nenhuma entrada adicional.

**Restrição:** O tipo de geração `"LowPoly"` não pode ser usado com o modelo `"3.1"`.

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `model_file` | STRING | Uma saída legada para compatibilidade com versões anteriores. |
| `GLB` | FILE3DGLB | O modelo 3D gerado no formato de arquivo GLB. |
| `OBJ` | FILE3DOBJ | O modelo 3D gerado no formato de arquivo OBJ. |
