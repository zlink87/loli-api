> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokVideoNode/fr.md)

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"grok-imagine-video-beta"` | Le modèle à utiliser pour la génération de vidéo. |
| `prompt` | STRING | Oui | - | Description textuelle de la vidéo souhaitée. |
| `resolution` | COMBO | Oui | `"480p"`<br>`"720p"` | La résolution de la vidéo en sortie. |
| `aspect_ratio` | COMBO | Oui | `"auto"`<br>`"16:9"`<br>`"4:3"`<br>`"3:2"`<br>`"1:1"`<br>`"2:3"`<br>`"3:4"`<br>`"9:16"` | Le format d'image de la vidéo en sortie. |
| `duration` | INT | Oui | 1 à 15 | La durée de la vidéo en sortie en secondes (par défaut : 6). |
| `seed` | INT | Oui | 0 à 2147483647 | Graine pour déterminer si le nœud doit être réexécuté ; les résultats réels sont non déterministes quelle que soit la graine (par défaut : 0). |
| `image` | IMAGE | Non | - | Une image d'entrée optionnelle à animer. |

**Note :** Si une `image` est fournie, une seule image est prise en charge. Fournir plusieurs images provoquera une erreur.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | La vidéo générée. |
