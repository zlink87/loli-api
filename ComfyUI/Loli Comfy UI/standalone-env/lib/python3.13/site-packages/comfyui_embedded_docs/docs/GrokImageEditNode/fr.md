> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageEditNode/fr.md)

Le nœud Grok Image Edit modifie une image existante en fonction d'une instruction textuelle. Il utilise l'API Grok pour générer une ou plusieurs nouvelles images qui sont des variations de l'entrée, guidées par votre description.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"grok-imagine-image-beta"` | Le modèle d'IA spécifique à utiliser pour l'édition d'image. |
| `image` | IMAGE | Oui | | L'image d'entrée à éditer. Une seule image est prise en charge. |
| `prompt` | STRING | Oui | | L'instruction textuelle utilisée pour générer l'image éditée. |
| `resolution` | COMBO | Oui | `"1K"` | La résolution de l'image de sortie. |
| `number_of_images` | INT | Non | 1 à 10 | Nombre d'images éditées à générer (par défaut : 1). |
| `seed` | INT | Non | 0 à 2147483647 | Graine pour déterminer si le nœud doit être réexécuté ; les résultats réels sont non déterministes quelle que soit la graine (par défaut : 0). |

**Note :** L'entrée `image` doit contenir exactement une image. Fournir plusieurs images provoquera une erreur.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | IMAGE | L'image ou les images éditées générées par le nœud. Si `number_of_images` est supérieur à 1, les sorties sont concaténées en un lot. |
