> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/fr.md)

Ce nœud améliore les images basse résolution en les suréchantillonnant vers une super-résolution, en supprimant les artefacts et le bruit. Il utilise une API externe pour traiter l'image et peut ajuster automatiquement la taille d'entrée pour rester dans les limites de traitement. La taille de sortie maximale autorisée est de 4 mégapixels.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Oui | `"generative_portrait"`<br>`"generative"` | Le modèle d'amélioration à utiliser. |
| `image` | IMAGE | Oui | - | L'image d'entrée à améliorer. |
| `upscale_factor` | INT | Oui | `1`<br>`2`<br>`4` | Le facteur par lequel les dimensions de l'image seront augmentées. |
| `auto_downscale` | BOOLEAN | Non | - | Réduit automatiquement l'image d'entrée si la sortie dépasserait la limite. (par défaut : `False`) |

**Note :** Le nœud générera une erreur si la taille de sortie calculée (hauteur d'entrée × upscale_factor × largeur d'entrée × upscale_factor) dépasse 4 000 000 pixels (4MP) et que `auto_downscale` est désactivé. Lorsque `auto_downscale` est activé, le nœud tentera de réduire l'image d'entrée pour qu'elle tienne dans la limite avant d'appliquer le facteur de suréchantillonnage demandé.

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `image` | IMAGE | L'image de sortie améliorée et suréchantillonnée. |
