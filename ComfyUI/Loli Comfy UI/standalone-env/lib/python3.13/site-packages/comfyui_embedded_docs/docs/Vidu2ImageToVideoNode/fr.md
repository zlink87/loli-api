> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ImageToVideoNode/fr.md)

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | Le modèle Vidu2 à utiliser pour la génération de vidéo. Les différents modèles offrent des compromis variables entre vitesse et qualité. |
| `image` | IMAGE | Oui | - | Une image à utiliser comme image de départ pour la vidéo générée. Une seule image est autorisée. |
| `prompt` | STRING | Non | - | Une description textuelle optionnelle pour guider la génération de la vidéo (maximum 2000 caractères). La valeur par défaut est une chaîne vide. |
| `duration` | INT | Oui | 1 à 10 | La durée de la vidéo générée, en secondes. La valeur par défaut est 5. |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de départ pour la génération de nombres aléatoires, afin d'assurer des résultats reproductibles. La valeur par défaut est 1. |
| `resolution` | COMBO | Oui | `"720p"`<br>`"1080p"` | La résolution de sortie de la vidéo générée. |
| `movement_amplitude` | COMBO | Oui | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | L'amplitude du mouvement des objets dans le cadre. |

**Contraintes :**

* L'entrée `image` doit contenir exactement une image.
* Le rapport d'aspect de l'image d'entrée doit être compris entre 1:4 et 4:1.
* Le texte du `prompt` est limité à un maximum de 2000 caractères.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo généré. |
