> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/EmptyAceStep1.5LatentAudio/fr.md)

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `seconds` | FLOAT | Non | 1.0 - 1000.0 | La durée de l'audio à générer, en secondes (par défaut : 120.0). |
| `batch_size` | INT | Non | 1 - 4096 | Le nombre d'images latentes dans le lot (par défaut : 1). |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `LATENT` | LATENT | Un tenseur latent vide représentant un audio silencieux, avec un identifiant de type "audio". |
