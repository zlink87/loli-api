> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/CreateList/fr.md)

Le nœud Create List combine plusieurs entrées en une seule liste séquentielle. Il prend un nombre quelconque d'entrées du même type de données et les concatène dans l'ordre où elles sont connectées. Ce nœud est utile pour préparer des lots de données, tels que des images ou du texte, à être traités par d'autres nœuds dans un flux de travail.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `input_*` | Variable | Oui | Toute | Un nombre variable de prises d'entrée. Vous pouvez ajouter plus d'entrées en cliquant sur l'icône plus (+). Toutes les entrées doivent être du même type de données (par exemple, toutes IMAGE ou toutes STRING). |

**Note :** Le nœud créera automatiquement de nouvelles prises d'entrée au fur et à mesure que vous connectez des éléments. Toutes les entrées connectées doivent partager le même type de données pour que le nœud fonctionne correctement.

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `list` | Variable | Une liste unique contenant tous les éléments des entrées connectées, concaténés dans l'ordre où ils ont été fournis. Le type de données de sortie correspond au type de données d'entrée. |
