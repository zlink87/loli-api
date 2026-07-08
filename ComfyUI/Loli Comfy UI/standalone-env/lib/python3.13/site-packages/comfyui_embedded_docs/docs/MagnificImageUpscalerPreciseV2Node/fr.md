> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerPreciseV2Node/fr.md)

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Oui | - | L'image d'entrée à suréchantillonner. Exactement une image est requise. Les dimensions minimales sont de 160x160 pixels. Le rapport d'aspect doit être compris entre 1:3 et 3:1. |
| `scale_factor` | STRING | Oui | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | Le multiplicateur de suréchantillonnage souhaité. |
| `flavor` | STRING | Oui | `"sublime"`<br>`"photo"`<br>`"photo_denoiser"` | Le style de traitement. "sublime" est pour un usage général, "photo" est optimisé pour les photographies, et "photo_denoiser" est pour les photos bruitées. |
| `sharpen` | INT | Non | 0 à 100 | Contrôle l'intensité de l'accentuation de l'image pour augmenter la définition et la clarté des contours. Des valeurs plus élevées produisent un résultat plus net. Par défaut : 7. |
| `smart_grain` | INT | Non | 0 à 100 | Ajoute un grain intelligent ou une amélioration de la texture pour éviter que l'image suréchantillonnée ne paraisse trop lisse ou artificielle. Par défaut : 7. |
| `ultra_detail` | INT | Non | 0 à 100 | Contrôle la quantité de détails fins, de textures et de micro-détails ajoutés pendant le processus de suréchantillonnage. Par défaut : 30. |
| `auto_downscale` | BOOLEAN | Non | - | Lorsqu'il est activé, le nœud réduira automatiquement l'image d'entrée si les dimensions de sortie calculées dépasseraient la résolution maximale autorisée de 10060x10060 pixels. Cela aide à prévenir les erreurs mais peut affecter la qualité. Par défaut : Faux. |

**Note :** Si `auto_downscale` est désactivé et que la taille de sortie demandée (dimensions d'entrée × `scale_factor`) dépasse 10060x10060 pixels, le nœud générera une erreur.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `image` | IMAGE | L'image suréchantillonnée résultante. |
