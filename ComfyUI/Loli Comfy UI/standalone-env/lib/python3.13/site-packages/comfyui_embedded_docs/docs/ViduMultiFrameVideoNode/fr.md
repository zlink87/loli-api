> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ViduMultiFrameVideoNode/fr.md)

Ce nœud génère une vidéo en créant des transitions entre plusieurs images clés. Il part d'une image initiale et anime une séquence d'images finales et de prompts définis par l'utilisateur, produisant un seul fichier vidéo en sortie.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
| :--- | :--- | :--- | :--- | :--- |
| `model` | COMBO | Oui | `"viduq2-pro"`<br>`"viduq2-turbo"` | Le modèle Vidu à utiliser pour la génération de vidéo. |
| `start_image` | IMAGE | Oui | - | L'image de la trame de départ. Le rapport d'aspect doit être compris entre 1:4 et 4:1. |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de seed pour la génération de nombres aléatoires afin d'assurer des résultats reproductibles (par défaut : 1). |
| `resolution` | COMBO | Oui | `"720p"`<br>`"1080p"` | La résolution de la vidéo de sortie. |
| `frames` | DYNAMICCOMBO | Oui | `"2"`<br>`"3"`<br>`"4"`<br>`"5"`<br>`"6"`<br>`"7"`<br>`"8"`<br>`"9"` | Nombre de transitions d'images clés (2-9). La sélection d'une valeur révèle dynamiquement les entrées requises pour chaque trame. |

**Entrées pour les trames (révélées dynamiquement) :**
Lorsque vous sélectionnez une valeur pour `frames` (par exemple, "3"), le nœud affichera un ensemble correspondant d'entrées requises pour chaque transition. Pour chaque trame `i` de 1 au nombre sélectionné, vous devez fournir :

* `end_image{i}` (IMAGE) : L'image cible pour cette transition. Le rapport d'aspect doit être compris entre 1:4 et 4:1.
* `prompt{i}` (STRING) : Une description textuelle guidant la transition vers cette trame (maximum 2000 caractères).
* `duration{i}` (INT) : La durée en secondes pour ce segment de transition spécifique.

## Sorties

| Nom de la sortie | Type de données | Description |
| :--- | :--- | :--- |
| `output` | VIDEO | Le fichier vidéo généré contenant toutes les transitions animées. |
