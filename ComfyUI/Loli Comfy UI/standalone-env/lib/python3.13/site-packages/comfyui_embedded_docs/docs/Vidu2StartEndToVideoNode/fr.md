> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2StartEndToVideoNode/fr.md)

Ce nœud génère une vidéo en interpolant entre une image de départ et une image de fin fournies, guidé par une description textuelle. Il utilise un modèle Vidu spécifié pour créer une transition fluide entre les deux images sur une durée définie.

## Entrées

| Paramètre | Type de Données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | Le modèle Vidu à utiliser pour la génération de la vidéo. |
| `first_frame` | IMAGE | Oui | - | L'image de départ pour la séquence vidéo. Une seule image est autorisée. |
| `end_frame` | IMAGE | Oui | - | L'image de fin pour la séquence vidéo. Une seule image est autorisée. |
| `prompt` | STRING | Oui | - | Une description textuelle guidant la génération de la vidéo (maximum 2000 caractères). |
| `duration` | INT | Non | 2 à 8 | La durée de la vidéo générée en secondes (par défaut : 5). |
| `seed` | INT | Non | 0 à 2147483647 | Un nombre utilisé pour initialiser la génération aléatoire afin d'obtenir des résultats reproductibles (par défaut : 1). |
| `resolution` | COMBO | Non | `"720p"`<br>`"1080p"` | La résolution de sortie de la vidéo générée. |
| `movement_amplitude` | COMBO | Non | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | L'amplitude du mouvement des objets dans le cadre. |

**Note :** Les images `first_frame` et `end_frame` doivent avoir des rapports d'aspect similaires. Le nœud vérifiera que leurs rapports d'aspect se situent dans une plage relative de 0,8 à 1,25.

## Sorties

| Nom de Sortie | Type de Données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo généré. |
