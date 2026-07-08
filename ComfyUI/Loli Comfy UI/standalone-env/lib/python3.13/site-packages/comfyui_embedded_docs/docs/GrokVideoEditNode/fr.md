> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokVideoEditNode/fr.md)

Ce nœud utilise l'API Grok pour modifier une vidéo existante à partir d'une consigne textuelle. Il télécharge votre vidéo, envoie une requête au modèle d'IA pour la modifier selon votre description, et renvoie la nouvelle vidéo générée.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"grok-imagine-video-beta"` | Le modèle d'IA à utiliser pour l'édition vidéo. |
| `prompt` | STRING | Oui | N/A | Description textuelle de la vidéo souhaitée. |
| `video` | VIDEO | Oui | N/A | La vidéo d'entrée à éditer. La durée maximale prise en charge est de 8,7 secondes et la taille de fichier maximale est de 50 Mo. |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de départ (seed) pour déterminer si le nœud doit être réexécuté. Les résultats réels sont non déterministes, quelle que soit la valeur du seed (par défaut : 0). |

**Contraintes :**

* La vidéo d'entrée `video` doit avoir une durée comprise entre 1 et 8,7 secondes.
* La taille du fichier vidéo d'entrée `video` ne doit pas dépasser 50 Mo.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `video` | VIDEO | La vidéo éditée générée par le modèle d'IA. |
