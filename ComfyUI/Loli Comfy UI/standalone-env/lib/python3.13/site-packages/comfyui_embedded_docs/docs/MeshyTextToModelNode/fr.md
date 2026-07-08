> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextToModelNode/fr.md)

## Vue d'ensemble

Le nœud Meshy : Text to Model utilise l'API Meshy pour générer un modèle 3D à partir d'une description textuelle. Il envoie une requête à l'API avec votre prompt et vos paramètres, puis attend que la génération soit terminée et télécharge les fichiers du modèle résultant.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"latest"` | Spécifie la version du modèle d'IA à utiliser. Actuellement, seule la version "latest" est disponible. |
| `prompt` | STRING | Oui | - | La description textuelle du modèle 3D que vous souhaitez générer. Doit contenir entre 1 et 600 caractères. |
| `style` | COMBO | Oui | `"realistic"`<br>`"sculpture"` | Le style artistique pour le modèle 3D généré. |
| `should_remesh` | DYNAMIC COMBO | Oui | `"true"`<br>`"false"` | Contrôle si le maillage généré est traité. Lorsqu'il est défini sur "false", le nœud renvoie un maillage triangulaire non traité. Sélectionner "true" révèle des paramètres supplémentaires pour la topologie et le nombre de polygones. |
| `topology` | COMBO | Non* | `"triangle"`<br>`"quad"` | Le type de polygone cible pour le modèle retopologisé. Ce paramètre n'est disponible et requis que lorsque `should_remesh` est défini sur "true". |
| `target_polycount` | INT | Non* | 100 - 300000 | Le nombre cible de polygones pour le modèle retopologisé. La valeur par défaut est 300000. Ce paramètre n'est disponible et requis que lorsque `should_remesh` est défini sur "true". |
| `symmetry_mode` | COMBO | Oui | `"auto"`<br>`"on"`<br>`"off"` | Contrôle la symétrie dans le modèle généré. |
| `pose_mode` | COMBO | Oui | `""`<br>`"A-pose"`<br>`"T-pose"` | Spécifie le mode de pose pour le modèle généré. Une chaîne vide signifie qu'aucune pose spécifique n'est demandée. |
| `seed` | INT | Oui | 0 - 2147483647 | Une valeur de seed pour la génération. Définir ce paramètre contrôle si le nœud doit être réexécuté, mais les résultats sont non déterministes quelle que soit la valeur du seed. La valeur par défaut est 0. |

*Note : Les paramètres `topology` et `target_polycount` sont conditionnellement requis. Ils n'apparaissent et doivent être définis que lorsque le paramètre `should_remesh` est défini sur "true".

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Le nom de fichier du modèle GLB généré. Cette sortie est fournie pour la rétrocompatibilité. |
| `meshy_task_id` | MESHY_TASK_ID | L'identifiant unique de la tâche de l'API Meshy. |
| `GLB` | FILE3DGLB | Le fichier du modèle 3D généré au format GLB. |
| `FBX` | FILE3DFBX | Le fichier du modèle 3D généré au format FBX. |
