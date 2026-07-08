> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerCreativeNode/fr.md)

Ce nœud utilise le service Magnific AI pour suréchantillonner et améliorer créativement une image. Il vous permet de guider l'amélioration avec une invite textuelle, de choisir un style spécifique à optimiser, et de contrôler divers aspects du processus créatif comme le détail, la ressemblance à l'original et la force de stylisation. Le nœud produit une image suréchantillonnée selon le facteur choisi (2x, 4x, 8x ou 16x), avec une taille de sortie maximale de 25,3 mégapixels.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Oui | - | L'image d'entrée à suréchantillonner et améliorer. |
| `prompt` | STRING | Non | - | Une description textuelle pour guider l'amélioration créative de l'image. Ce paramètre est optionnel (par défaut : vide). |
| `scale_factor` | COMBO | Oui | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | Le facteur par lequel les dimensions de l'image seront suréchantillonnées. |
| `optimized_for` | COMBO | Oui | `"standard"`<br>`"soft_portraits"`<br>`"hard_portraits"`<br>`"art_n_illustration"`<br>`"videogame_assets"`<br>`"nature_n_landscapes"`<br>`"films_n_photography"`<br>`"3d_renders"`<br>`"science_fiction_n_horror"` | Le style ou type de contenu pour lequel optimiser le processus d'amélioration. |
| `creativity` | INT | Non | -10 à 10 | Contrôle le niveau d'interprétation créative appliqué à l'image (par défaut : 0). |
| `hdr` | INT | Non | -10 à 10 | Le niveau de définition et de détail (par défaut : 0). |
| `resemblance` | INT | Non | -10 à 10 | Le niveau de ressemblance à l'image originale (par défaut : 0). |
| `fractality` | INT | Non | -10 à 10 | La force de l'invite et la complexité par pixel carré (par défaut : 0). |
| `engine` | COMBO | Oui | `"automatic"`<br>`"magnific_illusio"`<br>`"magnific_sharpy"`<br>`"magnific_sparkle"` | Le moteur d'IA spécifique à utiliser pour le traitement. |
| `auto_downscale` | BOOLEAN | Non | - | Lorsqu'activé, le nœud réduira automatiquement l'image d'entrée si le suréchantillonnage demandé dépasserait la taille de sortie maximale autorisée de 25,3 mégapixels (par défaut : Faux). |

**Contraintes :**

* L'`image` d'entrée doit être exactement une image.
* L'image d'entrée doit avoir une hauteur et une largeur minimales de 160 pixels.
* Le rapport d'aspect de l'image d'entrée doit être compris entre 1:3 et 3:1.
* La taille de sortie finale (dimensions d'entrée multipliées par le `scale_factor`) ne peut pas dépasser 25 300 000 pixels. Si `auto_downscale` est désactivé et que cette limite serait dépassée, le nœud générera une erreur.

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `image` | IMAGE | L'image de sortie améliorée créativement et suréchantillonnée. |
