> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypass/fr.md)

## Vue d'ensemble

Le nœud LoraLoaderBypass applique un LoRA (Low-Rank Adaptation) à un modèle de diffusion et à un modèle CLIP dans un mode spécial dit "bypass". Contrairement à un chargeur LoRA standard, cette méthode ne modifie pas de façon permanente les poids du modèle de base. Elle calcule plutôt la sortie en ajoutant l'effet du LoRA à la passe avant normale du modèle, ce qui est utile pour l'entraînement ou lorsque l'on travaille avec des modèles dont les poids sont déchargés.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Oui | - | Le modèle de diffusion auquel le LoRA sera appliqué. |
| `clip` | CLIP | Oui | - | Le modèle CLIP auquel le LoRA sera appliqué. |
| `lora_name` | COMBO | Oui | *Liste des fichiers LoRA disponibles* | Le nom du fichier LoRA à appliquer. Les options sont chargées depuis le dossier `loras`. |
| `strength_model` | FLOAT | Oui | -100.0 à 100.0 | L'intensité de la modification du modèle de diffusion. Cette valeur peut être négative (par défaut : 1.0). |
| `strength_clip` | FLOAT | Oui | -100.0 à 100.0 | L'intensité de la modification du modèle CLIP. Cette valeur peut être négative (par défaut : 1.0). |

**Note :** Si `strength_model` et `strength_clip` sont tous deux définis sur 0, le nœud retournera les entrées `model` et `clip` originales, non modifiées, sans traitement.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `MODEL` | MODEL | Le modèle de diffusion avec le LoRA appliqué en mode bypass. |
| `CLIP` | CLIP | Le modèle CLIP avec le LoRA appliqué en mode bypass. |
