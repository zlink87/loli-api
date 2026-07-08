> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeZImageOmni/fr.md)

Le nœud TextEncodeZImageOmni est un nœud de conditionnement avancé qui encode une invite textuelle ainsi que des images de référence optionnelles dans un format de conditionnement adapté aux modèles de génération d'image. Il peut traiter jusqu'à trois images, en les encodant optionnellement avec un encodeur visuel et/ou un VAE pour produire des latents de référence, et intègre ces références visuelles à l'invite textuelle en utilisant une structure de modèle spécifique.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Oui | | Le modèle CLIP utilisé pour la tokenisation et l'encodage de l'invite textuelle. |
| `image_encoder` | CLIPVision | Non | | Un modèle encodeur visuel optionnel. S'il est fourni, il sera utilisé pour encoder les images d'entrée, et les plongements résultants seront ajoutés au conditionnement. |
| `prompt` | STRING | Oui | | L'invite textuelle à encoder. Ce champ prend en charge l'entrée multiligne et les invites dynamiques. |
| `auto_resize_images` | BOOLEAN | Non | | Lorsqu'elle est activée (par défaut : True), les images d'entrée seront automatiquement redimensionnées en fonction de leur surface en pixels avant d'être transmises au VAE pour l'encodage. |
| `vae` | VAE | Non | | Un modèle VAE optionnel. S'il est fourni, il sera utilisé pour encoder les images d'entrée en représentations latentes, qui sont ajoutées au conditionnement en tant que latents de référence. |
| `image1` | IMAGE | Non | | La première image de référence optionnelle. |
| `image2` | IMAGE | Non | | La deuxième image de référence optionnelle. |
| `image3` | IMAGE | Non | | La troisième image de référence optionnelle. |

**Note :** Le nœud peut accepter un maximum de trois images (`image1`, `image2`, `image3`). Les entrées `image_encoder` et `vae` ne sont utilisées que si au moins une image est fournie. Lorsque `auto_resize_images` est True et qu'un `vae` est connecté, les images sont redimensionnées pour avoir une surface totale en pixels proche de 1024x1024 avant l'encodage.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | Le conditionnement final en sortie, qui contient l'invite textuelle encodée et peut inclure les plongements d'image encodés et/ou les latents de référence si des images ont été fournies. |
