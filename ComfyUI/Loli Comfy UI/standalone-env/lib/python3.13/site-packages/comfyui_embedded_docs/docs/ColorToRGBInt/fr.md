> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ColorToRGBInt/fr.md)

## ## Aperçu général

Le nœud ColorToRGBInt convertit une couleur spécifiée au format hexadécimal en une valeur entière unique. Il prend une chaîne de caractères représentant une couleur, comme `#FF5733`, et calcule l'entier RGB correspondant en combinant les composantes rouge, verte et bleue.

## ## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `color` | STRING | Oui | N/A | Une valeur de couleur au format hexadécimal `#RRGGBB`. |

**Note :** La chaîne de caractères d'entrée `color` doit comporter exactement 7 caractères et commencer par le symbole `#`, suivi de six chiffres hexadécimaux (par exemple, `#FF0000` pour le rouge). Le nœud générera une erreur si le format est incorrect.

## ## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `rgb_int` | INT | La valeur entière RGB calculée. Elle est dérivée de la formule : `(Rouge * 65536) + (Vert * 256) + Bleu`. |
