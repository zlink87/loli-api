> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageSkinEnhancerNode/fr.md)

Le nœud Magnific Image Skin Enhancer applique un traitement IA spécialisé aux images de portrait pour améliorer l'apparence de la peau. Il propose trois modes distincts pour différents objectifs d'amélioration : créatif pour des effets artistiques, fidèle pour préserver l'apparence originale, et flexible pour des améliorations ciblées comme l'éclairage ou le réalisme. Le nœud télécharge l'image vers une API externe pour le traitement et renvoie le résultat amélioré.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Oui | - | L'image de portrait à améliorer. |
| `sharpen` | INT | Non | 0 à 100 | Niveau d'intensité de l'accentuation (par défaut : 0). |
| `smart_grain` | INT | Non | 0 à 100 | Niveau d'intensité du grain intelligent (par défaut : 2). |
| `mode` | COMBO | Oui | `"creative"`<br>`"faithful"`<br>`"flexible"` | Le mode de traitement à utiliser. `"creative"` est pour une amélioration artistique, `"faithful"` pour préserver l'apparence originale, et `"flexible"` pour une optimisation ciblée. |
| `skin_detail` | INT | Non | 0 à 100 | Niveau d'amélioration des détails de la peau. Cette entrée n'est disponible et requise que lorsque le `mode` est défini sur `"faithful"` (par défaut : 80). |
| `optimized_for` | COMBO | Non | `"enhance_skin"`<br>`"improve_lighting"`<br>`"enhance_everything"`<br>`"transform_to_real"`<br>`"no_make_up"` | Cible d'optimisation de l'amélioration. Cette entrée n'est disponible et requise que lorsque le `mode` est défini sur `"flexible"`. |

**Contraintes :**

* Le nœud accepte exactement une image en entrée.
* L'image d'entrée doit avoir une hauteur et une largeur minimales de 160 pixels.
* Le paramètre `skin_detail` n'est actif que lorsque le `mode` est défini sur `"faithful"`.
* Le paramètre `optimized_for` n'est actif que lorsque le `mode` est défini sur `"flexible"`.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `image` | IMAGE | L'image de portrait améliorée. |
