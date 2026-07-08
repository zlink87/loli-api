> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3TextToVideoNode/fr.md)

Le nœud Vidu Q3 Text-to-Video Generation crée une vidéo à partir d'une description textuelle. Il utilise le modèle Vidu Q3 Pro pour générer un contenu vidéo basé sur votre prompt, vous permettant de contrôler la durée, la résolution et le format d'image de la vidéo.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq3-pro"` | Modèle à utiliser pour la génération de vidéo. La sélection de cette option révèle des paramètres de configuration supplémentaires pour le format d'image, la résolution, la durée et l'audio. |
| `model.aspect_ratio` | COMBO | Oui* | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | Le format d'image de la vidéo de sortie. Ce paramètre est révélé lorsque le `model` est sélectionné. |
| `model.resolution` | COMBO | Oui* | `"720p"`<br>`"1080p"` | Résolution de la vidéo de sortie. Ce paramètre est révélé lorsque le `model` est sélectionné. |
| `model.duration` | INT | Oui* | 1 à 16 | Durée de la vidéo de sortie en secondes (par défaut : 5). Ce paramètre est révélé lorsque le `model` est sélectionné. |
| `model.audio` | BOOLEAN | Oui* | Vrai/Faux | Lorsqu'il est activé, produit une vidéo avec du son (incluant dialogues et effets sonores) (par défaut : Faux). Ce paramètre est révélé lorsque le `model` est sélectionné. |
| `prompt` | STRING | Oui | N/A | Une description textuelle pour la génération de vidéo, avec une longueur maximale de 2000 caractères. |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de seed pour contrôler l'aléatoire de la génération (par défaut : 1). |

*Note : Les paramètres `aspect_ratio`, `resolution`, `duration` et `audio` sont requis une fois le `model` sélectionné, car ils font partie de sa configuration.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `video` | VIDEO | Le fichier vidéo généré. |
