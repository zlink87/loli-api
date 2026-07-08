> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedFlashVSRNode/fr.md)

Le WavespeedFlashVSRNode est un suréchantillonneur vidéo rapide et de haute qualité qui augmente la résolution et restaure la netteté des séquences de basse résolution ou floues. Il traite une vidéo d'entrée et produit une nouvelle vidéo à une résolution supérieure choisie par l'utilisateur.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `video` | VIDEO | Oui | N/A | Le fichier vidéo d'entrée à suréchantillonner. |
| `target_resolution` | STRING | Oui | `"720p"`<br>`"1080p"`<br>`"2K"`<br>`"4K"` | La résolution souhaitée pour la vidéo de sortie suréchantillonnée. |

**Contraintes d'entrée :**

* Le fichier `video` d'entrée doit être au format conteneur MP4.
* La durée de la `video` d'entrée doit être comprise entre 5 secondes et 10 minutes (600 secondes).

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `output` | VIDEO | Le fichier vidéo suréchantillonné à la résolution cible sélectionnée. |
