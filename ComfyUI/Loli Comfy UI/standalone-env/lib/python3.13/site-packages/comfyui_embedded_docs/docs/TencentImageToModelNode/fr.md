> Cette documentation a été générée par IA. Si vous trouvez des erreurs ou avez des suggestions d'amélioration, n'hésitez pas à contribuer ! [Modifier sur GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/fr.md)

Ce nœud utilise l'API Hunyuan3D Pro de Tencent pour générer un modèle 3D à partir d'une ou plusieurs images d'entrée. Il traite les images, les envoie à l'API et renvoie les fichiers du modèle 3D généré aux formats GLB et OBJ.

## Entrées

| Paramètre | Type de données | Requis | Plage | Description |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Oui | `"3.0"`<br>`"3.1"` | La version du modèle Hunyuan3D à utiliser. L'option LowPoly n'est pas disponible pour le modèle `3.1`. |
| `image` | IMAGE | Oui | - | L'image d'entrée principale utilisée pour générer le modèle 3D. |
| `image_left` | IMAGE | Non | - | Une image optionnelle du côté gauche de l'objet pour une génération multi-vues. |
| `image_right` | IMAGE | Non | - | Une image optionnelle du côté droit de l'objet pour une génération multi-vues. |
| `image_back` | IMAGE | Non | - | Une image optionnelle du côté arrière de l'objet pour une génération multi-vues. |
| `face_count` | INT | Oui | 40000 - 1500000 | Le nombre cible de faces pour le modèle 3D généré (par défaut : 500000). |
| `generate_type` | DYNAMICCOMBO | Oui | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | Le type de modèle 3D à générer. La sélection d'une option révèle des paramètres supplémentaires associés. |
| `generate_type.pbr` | BOOLEAN | Non | - | Active la génération de matériaux basés sur le rendu physique (PBR). Ce paramètre n'est visible que lorsque `generate_type` est défini sur "Normal" ou "LowPoly" (par défaut : Faux). |
| `generate_type.polygon_type` | COMBO | Non | `"triangle"`<br>`"quadrilateral"` | Le type de polygone à utiliser pour le maillage. Ce paramètre n'est visible que lorsque `generate_type` est défini sur "LowPoly". |
| `seed` | INT | Oui | 0 - 2147483647 | Une valeur de graine pour le processus de génération. La graine contrôle si le nœud doit être réexécuté ; les résultats sont non déterministes quelle que soit la graine (par défaut : 0). |

**Note :** Toutes les images d'entrée doivent avoir une largeur et une hauteur minimales de 128 pixels.

## Sorties

| Nom de sortie | Type de données | Description |
|-------------|-----------|-------------|
| `model_file` | STRING | Une sortie héritée pour la compatibilité ascendante. |
| `GLB` | FILE3DGLB | Le modèle 3D généré au format de fichier GLB (Binary GL Transmission Format). |
| `OBJ` | FILE3DOBJ | Le modèle 3D généré au format de fichier OBJ (Wavefront). |
