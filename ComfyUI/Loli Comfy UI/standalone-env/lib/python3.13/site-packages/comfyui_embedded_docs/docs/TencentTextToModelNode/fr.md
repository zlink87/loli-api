> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentTextToModelNode/fr.md)

Ce nœud utilise l'API Hunyuan3D Pro de Tencent pour générer un modèle 3D à partir d'une description textuelle. Il envoie une requête pour créer une tâche de génération, interroge le résultat et télécharge les fichiers finaux du modèle aux formats GLB et OBJ.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"3.0"`<br>`"3.1"` | La version du modèle Hunyuan3D à utiliser. L'option LowPoly n'est pas disponible pour le modèle `3.1`. |
| `prompt` | STRING | Oui | - | La description textuelle du modèle 3D à générer. Prend en charge jusqu'à 1024 caractères. |
| `face_count` | INT | Oui | 40000 - 1500000 | Le nombre cible de faces pour le modèle 3D généré. Par défaut : 500000. |
| `generate_type` | DYNAMICCOMBO | Oui | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | Le type de modèle 3D à générer. Les options disponibles et leurs paramètres associés sont :<br>- **Normal** : Génère un modèle standard. Inclut un paramètre `pbr` (par défaut : `False`).<br>- **LowPoly** : Génère un modèle à faible polygones. Inclut les paramètres `polygon_type` (`"triangle"` ou `"quadrilateral"`) et `pbr` (par défaut : `False`).<br>- **Geometry** : Génère un modèle uniquement géométrique. |
| `seed` | INT | Non | 0 - 2147483647 | Une valeur de seed pour la génération. Les résultats sont non déterministes, quel que soit le seed. Définir un nouveau seed contrôle si le nœud doit être réexécuté. Par défaut : 0. |

**Note :** Le paramètre `generate_type` est dynamique. Sélectionner `"LowPoly"` révélera des entrées supplémentaires pour `polygon_type` et `pbr`. Sélectionner `"Normal"` révélera une entrée pour `pbr`. Sélectionner `"Geometry"` ne révélera aucune entrée supplémentaire.

**Contrainte :** Le type de génération `"LowPoly"` ne peut pas être utilisé avec le modèle `"3.1"`.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Une sortie héritée pour la rétrocompatibilité. |
| `GLB` | FILE3DGLB | Le modèle 3D généré au format de fichier GLB. |
| `OBJ` | FILE3DOBJ | Le modèle 3D généré au format de fichier OBJ. |
