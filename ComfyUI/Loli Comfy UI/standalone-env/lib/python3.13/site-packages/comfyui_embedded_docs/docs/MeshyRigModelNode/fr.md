> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRigModelNode/fr.md)

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `meshy_task_id` | STRING | Oui | N/A | L'identifiant unique de tâche provenant d'une opération Meshy précédente (par exemple, texte-à-3D ou image-à-3D) qui a généré le modèle à rigger. |
| `height_meters` | FLOAT | Oui | 0.1 à 15.0 | La hauteur approximative du modèle de personnage en mètres. Cela aide à la précision de la mise à l'échelle et du rigging (par défaut : 1.7). |
| `texture_image` | IMAGE | Non | N/A | L'image de texture de couleur de base avec UV déplié pour le modèle. |

**Note :** Le processus de rigging automatique n'est actuellement pas adapté aux maillages non texturés, aux actifs non humanoïdes, ou aux actifs humanoïdes dont la structure des membres et du corps n'est pas claire.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Une sortie héritée pour la compatibilité ascendante, contenant le nom de fichier du modèle GLB. |
| `rig_task_id` | STRING | L'identifiant unique de tâche pour cette opération de rigging, qui peut être utilisé pour référencer le résultat. |
| `GLB` | FILE3DGLB | Le modèle de personnage 3D riggé enregistré au format de fichier GLB. |
| `FBX` | FILE3DFBX | Le modèle de personnage 3D riggé enregistré au format de fichier FBX. |
