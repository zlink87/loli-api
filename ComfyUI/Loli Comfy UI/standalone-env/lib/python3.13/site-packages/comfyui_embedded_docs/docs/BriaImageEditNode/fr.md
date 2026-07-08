> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/BriaImageEditNode/fr.md)

Le nœud Bria FIBO Image Edit vous permet de modifier une image existante à l'aide d'une instruction textuelle. Il envoie l'image et votre prompt à l'API Bria, qui utilise le modèle FIBO pour générer une nouvelle version modifiée de l'image en fonction de votre demande. Vous pouvez également fournir un masque pour limiter les modifications à une zone spécifique.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"FIBO"` | La version du modèle à utiliser pour l'édition d'image. |
| `image` | IMAGE | Oui | - | L'image d'entrée que vous souhaitez modifier. |
| `prompt` | STRING | Non | - | L'instruction textuelle décrivant comment modifier l'image (par défaut : vide). |
| `negative_prompt` | STRING | Non | - | Texte décrivant ce que vous ne voulez pas voir apparaître dans l'image modifiée (par défaut : vide). |
| `structured_prompt` | STRING | Non | - | Une chaîne contenant le prompt d'édition structuré au format JSON. Utilisez ceci à la place du prompt habituel pour un contrôle précis et programmatique (par défaut : vide). |
| `seed` | INT | Oui | 1 à 2147483647 | Un nombre utilisé pour initialiser la génération aléatoire, garantissant des résultats reproductibles (par défaut : 1). |
| `guidance_scale` | FLOAT | Oui | 3.0 à 5.0 | Contrôle à quel point l'image générée suit le prompt. Une valeur plus élevée entraîne une adhérence plus forte (par défaut : 3.0). |
| `steps` | INT | Oui | 20 à 50 | Le nombre d'étapes de dé-bruitage que le modèle effectuera (par défaut : 50). |
| `moderation` | DYNAMICCOMBO | Oui | `"true"`<br>`"false"` | Active ou désactive la modération de contenu. Sélectionner `"true"` révèle des options de modération supplémentaires. |
| `mask` | MASK | Non | - | Une image de masque optionnelle. Si elle est fournie, les modifications ne seront appliquées qu'aux zones masquées de l'image. |

**Contraintes importantes :**

* Vous devez fournir au moins l'une des entrées `prompt` ou `structured_prompt`. Elles ne peuvent pas être toutes les deux vides.
* Exactement une entrée `image` est requise.
* Lorsque le paramètre `moderation` est défini sur `"true"`, trois entrées booléennes supplémentaires deviennent disponibles : `prompt_content_moderation`, `visual_input_moderation` et `visual_output_moderation`.

## Sorties

| Nom de la sortie | Type de données | Description |
|-------------|-----------|-------------|
| `IMAGE` | IMAGE | L'image modifiée renvoyée par l'API Bria. |
| `structured_prompt` | STRING | Le prompt structuré qui a été utilisé ou généré pendant le processus d'édition. |
