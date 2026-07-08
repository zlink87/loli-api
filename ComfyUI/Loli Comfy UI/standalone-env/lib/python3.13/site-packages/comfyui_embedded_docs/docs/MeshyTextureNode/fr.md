> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextureNode/fr.md)

Le nœud Meshy : Texture applique des textures générées par IA à un modèle 3D. Il prend un identifiant de tâche provenant d'un nœud précédent de génération ou de conversion 3D Meshy et utilise soit une description textuelle, soit une image de référence pour créer de nouvelles textures pour le modèle. Le nœud renvoie le modèle texturé aux formats de fichiers GLB et FBX.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"latest"` | La version du modèle d'IA à utiliser pour la texturation. Actuellement, seule la version "latest" est disponible. |
| `meshy_task_id` | MESHY_TASK_ID | Oui | - | L'identifiant unique (ID de tâche) provenant d'une tâche précédente de génération ou de conversion 3D Meshy. Cela fournit le modèle 3D de base à texturer. |
| `enable_original_uv` | BOOLEAN | Non | - | Lorsqu'il est activé (par défaut : `True`), le nœud utilise le mapping UV d'origine du modèle téléchargé, préservant ainsi les textures existantes. Si le modèle n'a pas de mapping UV d'origine, la qualité de sortie peut être inférieure. |
| `pbr` | BOOLEAN | Non | - | Active la sortie de matériaux en rendu physiquement réaliste (PBR) pour le modèle texturé (par défaut : `False`). |
| `text_style_prompt` | STRING | Non | - | Une description textuelle du style de texture souhaité pour l'objet. Maximum 600 caractères. Ne peut pas être utilisé en même temps que `image_style`. |
| `image_style` | IMAGE | Non | - | Une image de référence 2D pour guider le processus de texturation. Ne peut pas être utilisée en même temps que `text_style_prompt`. |

**Contraintes des paramètres :**

* Vous devez fournir soit un `text_style_prompt`, soit une `image_style`, mais vous ne pouvez pas fournir les deux en même temps.
* Le `text_style_prompt` est limité à un maximum de 600 caractères.

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Le nom de fichier du modèle GLB généré. Cette sortie est fournie pour la rétrocompatibilité. |
| `meshy_task_id` | MODEL_TASK_ID | L'identifiant unique de la tâche pour ce travail de texturation, qui peut être utilisé pour référencer le résultat. |
| `GLB` | FILE3DGLB | Le modèle 3D texturé enregistré au format de fichier GLB. |
| `FBX` | FILE3DFBX | Le modèle 3D texturé enregistré au format de fichier FBX. |
