> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/VAEDecodeAudioTiled/fr.md)

Ce nœud convertit une représentation audio compressée (échantillons latents) en une forme d'onde audio en utilisant un Autoencodeur Variationnel (VAE). Il traite les données par sections plus petites et chevauchantes (tuiles) pour gérer l'utilisation de la mémoire, ce qui le rend adapté à la gestion de séquences audio plus longues.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `samples` | LATENT | Oui | N/A | La représentation latente compressée de l'audio à décoder. |
| `vae` | VAE | Oui | N/A | Le modèle d'Autoencodeur Variationnel utilisé pour effectuer le décodage. |
| `tile_size` | INT | Non | 32 à 8192 | La taille de chaque tuile de traitement. L'audio est décodé par sections de cette longueur pour économiser la mémoire (par défaut : 512). |
| `overlap` | INT | Non | 0 à 1024 | Le nombre d'échantillons par lesquels les tuiles adjacentes se chevauchent. Cela permet de réduire les artefacts aux limites entre les tuiles (par défaut : 64). |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | AUDIO | La forme d'onde audio décodée. |
