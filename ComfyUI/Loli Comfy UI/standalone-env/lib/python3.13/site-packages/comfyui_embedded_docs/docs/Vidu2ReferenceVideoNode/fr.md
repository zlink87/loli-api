> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ReferenceVideoNode/fr.md)

Le nœud Vidu2 Reference-to-Video Generation crée une vidéo à partir d'une description textuelle et de plusieurs images de référence. Vous pouvez définir jusqu'à sept sujets, chacun avec son propre ensemble d'images de référence, et les référencer dans la description en utilisant `@subject{subject_id}`. Le nœud génère une vidéo avec une durée, un format d'image et un mouvement configurables.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"viduq2"` | Le modèle d'IA à utiliser pour la génération de vidéo. |
| `subjects` | AUTOGROW | Oui | N/A | Pour chaque sujet, fournissez jusqu'à 3 images de référence (7 images maximum au total pour tous les sujets). Référencez-les dans les descriptions via `@subject{subject_id}`. |
| `prompt` | STRING | Oui | N/A | La description textuelle utilisée pour guider la génération de la vidéo. Lorsque le paramètre `audio` est activé, la vidéo inclura une voix générée et une musique de fond basées sur cette description. |
| `audio` | BOOLEAN | Non | N/A | Lorsqu'activé, la vidéo contiendra une voix générée et une musique de fond basées sur la description (par défaut : `False`). |
| `duration` | INT | Non | 1 à 10 | La durée de la vidéo générée en secondes (par défaut : `5`). |
| `seed` | INT | Non | 0 à 2147483647 | Un nombre utilisé pour contrôler l'aléatoire de la génération afin d'obtenir des résultats reproductibles (par défaut : `1`). |
| `aspect_ratio` | COMBO | Non | `"16:9"`<br>`"9:16"`<br>`"4:3"`<br>`"3:4"`<br>`"1:1"` | Le format de l'image vidéo. |
| `resolution` | COMBO | Non | `"720p"`<br>`"1080p"` | La résolution en pixels de la vidéo de sortie. |
| `movement_amplitude` | COMBO | Non | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | Contrôle l'amplitude du mouvement des objets dans le cadre. |

**Contraintes :**

* Le `prompt` doit comporter entre 1 et 2000 caractères.
* Vous pouvez définir plusieurs sujets, mais le nombre total d'images de référence pour tous les sujets ne doit pas dépasser 7.
* Chaque sujet individuel peut avoir un maximum de 3 images de référence.
* Chaque image de référence doit avoir un rapport largeur/hauteur compris entre 1:4 et 4:1.
* Chaque image de référence doit mesurer au moins 128 pixels en largeur et en hauteur.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo généré. |
