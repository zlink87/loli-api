> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/fr.md)

Le nœud Meshy : Modèle de Raffinement de Maquette prend un modèle 3D préalablement généré (maquette) et améliore sa qualité, en ajoutant éventuellement des textures. Il soumet une tâche de raffinement à l'API Meshy et renvoie les fichiers finaux du modèle 3D une fois le traitement terminé.

## Entrées

| Paramètre | Type de Données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"latest"` | Spécifie le modèle d'IA à utiliser pour le raffinement. Actuellement, seul le modèle "latest" (le plus récent) est disponible. |
| `meshy_task_id` | MESHY_TASK_ID | Oui | - | L'identifiant unique de la tâche du modèle maquette que vous souhaitez raffiner. |
| `enable_pbr` | BOOLEAN | Non | - | Génère des cartes PBR (métallique, rugosité, normale) en plus de la couleur de base. Note : ce paramètre doit être défini sur false lors de l'utilisation du style Sculpture, car le style Sculpture génère son propre jeu de cartes PBR. (par défaut : `False`) |
| `texture_prompt` | STRING | Non | - | Fournit une consigne textuelle pour guider le processus de texturation. Maximum 600 caractères. Ne peut pas être utilisé en même temps que 'texture_image'. (par défaut : chaîne vide) |
| `texture_image` | IMAGE | Non | - | Une seule des entrées 'texture_image' ou 'texture_prompt' peut être utilisée à la fois. (optionnel) |

**Note :** Les entrées `texture_prompt` et `texture_image` sont mutuellement exclusives. Vous ne pouvez pas fournir à la fois une consigne textuelle et une image pour la texturation dans la même opération.

## Sorties

| Nom de la Sortie | Type de Données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Le nom de fichier du modèle GLB généré. (Uniquement pour la rétrocompatibilité) |
| `meshy_task_id` | MESHY_TASK_ID | L'identifiant unique de la tâche de raffinement soumise. |
| `GLB` | FILE3DGLB | Le modèle 3D raffiné final au format GLB. |
| `FBX` | FILE3DFBX | Le modèle 3D raffiné final au format FBX. |
