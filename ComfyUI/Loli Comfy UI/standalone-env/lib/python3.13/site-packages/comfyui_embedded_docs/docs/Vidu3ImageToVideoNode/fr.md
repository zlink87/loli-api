> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3ImageToVideoNode/fr.md)

Le nœud Vidu Q3 Image-to-Vidéo génère une séquence vidéo à partir d'une image d'entrée. Il utilise le modèle Vidu Q3 Pro pour animer l'image, éventuellement guidé par une invite textuelle, et produit un fichier vidéo.

## Entrées

| Paramètre | Type de Données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq3-pro"` | Modèle à utiliser pour la génération de vidéo. |
| `model.resolution` | COMBO | Oui | `"720p"`<br>`"1080p"`<br>`"2K"` | Résolution de la vidéo de sortie. |
| `model.duration` | INT | Oui | 1 à 16 | Durée de la vidéo de sortie en secondes (par défaut : 5). |
| `model.audio` | BOOLEAN | Oui | `True` / `False` | Lorsqu'activé, produit une vidéo avec le son (incluant dialogues et effets sonores) (par défaut : False). |
| `image` | IMAGE | Oui | - | Image à utiliser comme première image de la vidéo générée. |
| `prompt` | STRING | Non | - | Une invite textuelle optionnelle pour guider la génération de la vidéo (max 2000 caractères) (par défaut : vide). |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de graine pour contrôler l'aléatoire de la génération (par défaut : 1). |

**Note :** L'`image` doit avoir un rapport d'aspect compris entre 1:4 et 4:1 (portrait à paysage). Le `prompt` est optionnel mais ne peut pas dépasser 2000 caractères.

## Sorties

| Nom de Sortie | Type de Données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo généré. |
