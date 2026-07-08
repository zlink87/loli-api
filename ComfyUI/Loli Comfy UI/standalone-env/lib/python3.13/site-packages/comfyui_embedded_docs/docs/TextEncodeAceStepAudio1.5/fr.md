> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/fr.md)

Le nœud TextEncodeAceStepAudio1.5 prépare le texte et les métadonnées liées à l'audio pour une utilisation avec le modèle AceStepAudio 1.5. Il prend des tags descriptifs, des paroles et des paramètres musicaux, puis utilise un modèle CLIP pour les convertir dans un format de conditionnement adapté à la génération audio.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Oui | N/A | Le modèle CLIP utilisé pour tokeniser et encoder le texte d'entrée. |
| `tags` | STRING | Oui | N/A | Tags descriptifs pour l'audio, tels que genre, ambiance ou instruments. Prend en charge l'entrée multiligne et les invites dynamiques. |
| `lyrics` | STRING | Oui | N/A | Les paroles de la piste audio. Prend en charge l'entrée multiligne et les invites dynamiques. |
| `seed` | INT | Non | 0 à 18446744073709551615 | Une valeur de graine aléatoire pour une génération reproductible. Dispose d'un widget `control_after_generate`. Valeur par défaut : 0. |
| `bpm` | INT | Non | 10 à 300 | Le tempo (battements par minute) pour l'audio généré. Valeur par défaut : 120. |
| `duration` | FLOAT | Non | 0.0 à 2000.0 | La durée souhaitée de l'audio en secondes. Valeur par défaut : 120.0. |
| `timesignature` | COMBO | Non | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | La signature rythmique musicale. |
| `language` | COMBO | Non | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | La langue du texte d'entrée. |
| `keyscale` | COMBO | Non | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | La tonalité et la gamme musicales (majeur ou mineur). |
| `generate_audio_codes` | BOOLEAN | Non | N/A | Active le LLM qui génère les codes audio. Cela peut être lent mais augmentera la qualité de l'audio généré. Désactivez cette option si vous donnez au modèle une référence audio. Valeur par défaut : True. |
| `cfg_scale` | FLOAT | Non | 0.0 à 100.0 | L'échelle de guidance sans classifieur. Des valeurs plus élevées font que la sortie suit plus étroitement l'invite. Valeur par défaut : 2.0. |
| `temperature` | FLOAT | Non | 0.0 à 2.0 | Une température d'échantillonnage. Des valeurs plus basses rendent la sortie plus déterministe. Valeur par défaut : 0.85. |
| `top_p` | FLOAT | Non | 0.0 à 2000.0 | La probabilité d'échantillonnage par noyau (top-p). Valeur par défaut : 0.9. |
| `top_k` | INT | Non | 0 à 100 | Le nombre de tokens de plus haute probabilité à considérer (top-k). Valeur par défaut : 0. |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | Les données de conditionnement, qui contiennent le texte encodé et les paramètres audio pour le modèle AceStepAudio 1.5. |
