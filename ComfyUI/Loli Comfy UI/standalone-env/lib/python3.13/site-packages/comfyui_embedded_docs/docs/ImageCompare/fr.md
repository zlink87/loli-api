> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ImageCompare/fr.md)

Le nœud Image Compare offre une interface visuelle pour comparer deux images côte à côte à l'aide d'un curseur déplaçable. Il est conçu comme un nœud de sortie, ce qui signifie qu'il ne transmet pas de données à d'autres nœuds mais affiche directement les images dans l'interface utilisateur pour inspection.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `image_a` | IMAGE | Non | - | La première image à comparer. |
| `image_b` | IMAGE | Non | - | La seconde image à comparer. |
| `compare_view` | IMAGECOMPARE | Oui | - | Le contrôle qui active la vue de comparaison avec curseur dans l'interface. |

**Note :** Ce nœud est un nœud de sortie. Bien que `image_a` et `image_b` soient optionnels, au moins une image doit être fournie pour que le nœud ait un effet visible. Le nœud affichera une zone vide pour toute entrée d'image qui n'est pas connectée.

## Sorties

Ce nœud est un nœud de sortie et ne produit aucune donnée de sortie pour être utilisée dans d'autres nœuds. Sa fonction est d'afficher les images fournies dans l'interface de ComfyUI.
