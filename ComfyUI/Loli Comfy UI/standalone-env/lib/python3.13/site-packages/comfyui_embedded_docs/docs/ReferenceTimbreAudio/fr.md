> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ReferenceTimbreAudio/fr.md)

Ce nœud définit une référence de timbre audio pour utilisation dans le processus "ace step 1.5". Il fonctionne en prenant une entrée de conditionnement et, optionnellement, une représentation latente de l'audio, puis attache ces données latentes au conditionnement pour qu'elles soient utilisées par les nœuds suivants dans le flux de travail.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `conditioning` | CONDITIONING | Oui | | Les données de conditionnement auxquelles les informations de référence audio seront attachées. |
| `latent` | LATENT | Non | | Une représentation latente optionnelle de l'audio de référence. Lorsqu'elle est fournie, ses échantillons sont ajoutés au conditionnement. |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `conditioning` | CONDITIONING | Les données de conditionnement modifiées, contenant désormais les latents du timbre audio de référence si l'entrée optionnelle `latent` a été fournie. |
