> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2TextToVideoNode/fr.md)

Le nœud Vidu2 Text-to-Video Generation crée une vidéo à partir d'une description textuelle. Il se connecte à une API externe pour générer un contenu vidéo basé sur votre prompt, vous permettant de contrôler la durée, le style visuel et le format de la vidéo.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq2"` | Le modèle d'IA à utiliser pour la génération vidéo. Un seul modèle est actuellement disponible. |
| `prompt` | STRING | Oui | - | Une description textuelle pour la génération vidéo, avec une longueur maximale de 2000 caractères. |
| `duration` | INT | Non | 1 à 10 | La durée de la vidéo générée en secondes. La valeur peut être ajustée à l'aide d'un curseur (par défaut : 5). |
| `seed` | INT | Non | 0 à 2147483647 | Un nombre utilisé pour contrôler l'aléatoire de la génération, permettant d'obtenir des résultats reproductibles. Il peut être contrôlé après la génération (par défaut : 1). |
| `aspect_ratio` | COMBO | Non | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | La relation proportionnelle entre la largeur et la hauteur de la vidéo. |
| `resolution` | COMBO | Non | `"720p"`<br>`"1080p"` | Les dimensions en pixels de la vidéo générée. |
| `background_music` | BOOLEAN | Non | - | Indique s'il faut ajouter une musique de fond à la vidéo générée (par défaut : Faux). |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo généré. |
