> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageNode/fr.md)

## Vue d'ensemble

Le nœud Grok Image génère une ou plusieurs images basées sur une description textuelle en utilisant le modèle d'IA Grok. Il envoie votre prompt à un service externe et renvoie les images générées sous forme de tenseurs qui peuvent être utilisés dans votre flux de travail.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"grok-imagine-image-beta"` | Le modèle Grok spécifique à utiliser pour la génération d'image. |
| `prompt` | STRING | Oui | N/A | Le prompt textuel utilisé pour générer l'image. Cette description guide l'IA sur ce qu'elle doit créer. |
| `aspect_ratio` | COMBO | Oui | `"1:1"`<br>`"2:3"`<br>`"3:2"`<br>`"3:4"`<br>`"4:3"`<br>`"9:16"`<br>`"16:9"`<br>`"9:19.5"`<br>`"19.5:9"`<br>`"9:20"`<br>`"20:9"`<br>`"1:2"`<br>`"2:1"` | Le rapport largeur/hauteur souhaité pour l'image générée. |
| `number_of_images` | INT | Non | 1 à 10 | Nombre d'images à générer (par défaut : 1). |
| `seed` | INT | Non | 0 à 2147483647 | Une valeur de seed pour déterminer si le nœud doit se ré-exécuter. Les résultats d'image réels sont non déterministes et varieront même avec le même seed (par défaut : 0). |

**Note :** Le paramètre `seed` est principalement utilisé pour contrôler quand le nœud se ré-exécute dans un flux de travail. En raison de la nature du service d'IA externe, les images générées ne seront pas reproductibles ou identiques d'une exécution à l'autre, même avec un seed identique.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | IMAGE | L'image générée ou un lot d'images. Si `number_of_images` est 1, un seul tenseur d'image est renvoyé. S'il est supérieur à 1, un lot de tenseurs d'images est renvoyé. |
