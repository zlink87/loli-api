> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ViduReferenceVideoNode/fr.md)

Le nœud Vidu Reference Video génère des vidéos à partir de plusieurs images de référence et d'une description textuelle. Il utilise des modèles d'IA pour créer un contenu vidéo cohérent basé sur les images fournies et la description. Le nœud prend en charge divers paramètres vidéo incluant la durée, le format d'image, la résolution et le contrôle du mouvement.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"vidu_q1"` | Nom du modèle pour la génération vidéo (par défaut : "vidu_q1") |
| `images` | IMAGE | Oui | - | Images à utiliser comme références pour générer une vidéo avec des sujets cohérents (maximum 7 images) |
| `prompt` | STRING | Oui | - | Description textuelle pour la génération vidéo |
| `duration` | INT | Non | 5-5 | Durée de la vidéo de sortie en secondes (par défaut : 5) |
| `seed` | INT | Non | 0-2147483647 | Graine pour la génération vidéo (0 pour aléatoire) (par défaut : 0) |
| `aspect_ratio` | COMBO | Non | `"16:9"`<br>`"9:16"`<br>`"1:1"`<br>`"4:3"`<br>`"3:4"`<br>`"21:9"`<br>`"9:21"` | Le format d'image de la vidéo de sortie (par défaut : "16:9") |
| `resolution` | COMBO | Non | `"480p"`<br>`"720p"`<br>`"1080p"`<br>`"1440p"`<br>`"2160p"` | Les valeurs prises en charge peuvent varier selon le modèle et la durée (par défaut : "1080p") |
| `movement_amplitude` | COMBO | Non | `"auto"`<br>`"low"`<br>`"medium"`<br>`"high"` | L'amplitude du mouvement des objets dans le cadre (par défaut : "auto") |

**Contraintes et limitations :**

- Le champ `prompt` est requis et ne peut pas être vide
- Maximum de 7 images autorisées pour référence
- Chaque image doit avoir un format d'image compris entre 1:4 et 4:1
- Chaque image doit avoir des dimensions minimales de 128x128 pixels
- La durée est fixée à 5 secondes

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | La vidéo générée basée sur les images de référence et la description |
