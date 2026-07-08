> Esta documentação foi gerada por IA. Se você encontrar erros ou tiver sugestões de melhoria, sinta-se à vontade para contribuir! [Editar no GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/pt-BR.md)

O nó TextEncodeAceStepAudio1.5 prepara texto e metadados relacionados ao áudio para uso com o modelo AceStepAudio 1.5. Ele recebe tags descritivas, letras e parâmetros musicais e, em seguida, usa um modelo CLIP para convertê-los em um formato de condicionamento adequado para geração de áudio.

## Entradas

| Parâmetro | Tipo de Dados | Obrigatório | Intervalo | Descrição |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Sim | N/A | O modelo CLIP usado para tokenizar e codificar o texto de entrada. |
| `tags` | STRING | Sim | N/A | Tags descritivas para o áudio, como gênero, clima ou instrumentos. Suporta entrada de múltiplas linhas e prompts dinâmicos. |
| `lyrics` | STRING | Sim | N/A | A letra da faixa de áudio. Suporta entrada de múltiplas linhas e prompts dinâmicos. |
| `seed` | INT | Não | 0 a 18446744073709551615 | Um valor de semente aleatória para geração reproduzível. Possui um widget `control_after_generate`. Padrão: 0. |
| `bpm` | INT | Não | 10 a 300 | A batida por minuto (BPM) para o áudio gerado. Padrão: 120. |
| `duration` | FLOAT | Não | 0.0 a 2000.0 | A duração desejada do áudio em segundos. Padrão: 120.0. |
| `timesignature` | COMBO | Não | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | A assinatura de tempo musical. |
| `language` | COMBO | Não | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | O idioma do texto de entrada. |
| `keyscale` | COMBO | Não | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | A tonalidade e escala musical (maior ou menor). |
| `generate_audio_codes` | BOOLEAN | Não | N/A | Ativa o LLM que gera códigos de áudio. Isso pode ser lento, mas aumentará a qualidade do áudio gerado. Desative isso se estiver fornecendo uma referência de áudio ao modelo. Padrão: Verdadeiro. |
| `cfg_scale` | FLOAT | Não | 0.0 a 100.0 | A escala de orientação livre de classificador. Valores mais altos fazem a saída seguir mais de perto o prompt. Padrão: 2.0. |
| `temperature` | FLOAT | Não | 0.0 a 2.0 | Uma temperatura de amostragem. Valores mais baixos tornam a saída mais determinística. Padrão: 0.85. |
| `top_p` | FLOAT | Não | 0.0 a 2000.0 | A probabilidade de amostragem por núcleo (top-p). Padrão: 0.9. |
| `top_k` | INT | Não | 0 a 100 | O número de tokens de maior probabilidade a serem considerados (top-k). Padrão: 0. |

## Saídas

| Nome da Saída | Tipo de Dados | Descrição |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | Os dados de condicionamento, que contêm o texto codificado e os parâmetros de áudio para o modelo AceStepAudio 1.5. |
