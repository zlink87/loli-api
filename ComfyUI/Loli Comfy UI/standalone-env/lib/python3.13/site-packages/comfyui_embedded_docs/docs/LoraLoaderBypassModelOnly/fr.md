> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypassModelOnly/fr.md)

Ce nœud applique une LoRA (Low-Rank Adaptation) à un modèle pour modifier son comportement, mais n'affecte que le composant modèle lui-même. Il charge un fichier LoRA spécifié et ajuste les poids du modèle selon une intensité donnée, laissant les autres composants comme l'encodeur de texte CLIP inchangés.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Oui | - | Le modèle de base auquel les ajustements LoRA seront appliqués. |
| `lora_name` | STRING | Oui | (Liste des fichiers LoRA disponibles) | Le nom du fichier LoRA à charger et à appliquer. Les options sont peuplées à partir des fichiers du répertoire `loras`. |
| `strength_model` | FLOAT | Oui | -100.0 à 100.0 | L'intensité de l'effet de la LoRA sur les poids du modèle. Une valeur positive applique la LoRA, une valeur négative applique l'inverse, et une valeur de 0 n'a aucun effet (par défaut : 1.0). |

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model` | MODEL | Le modèle modifié avec les ajustements LoRA appliqués à ses poids. |
