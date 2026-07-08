> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyTextureNode/tr.md)

Meshy: Texture Düğümü, bir 3B modele yapay zeka ile oluşturulmuş dokular uygular. Önceki bir Meshy 3B oluşturma veya dönüştürme düğümünden bir görev kimliği alır ve modele yeni dokular oluşturmak için bir metin açıklaması veya referans görseli kullanır. Düğüm, dokulu modeli GLB ve FBX dosya formatlarında çıktı olarak verir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"latest"` | Dokulama için kullanılacak yapay zeka modeli sürümü. Şu anda yalnızca "latest" (en son) sürüm mevcuttur. |
| `meshy_task_id` | MESHY_TASK_ID | Evet | - | Önceki bir Meshy 3B oluşturma veya dönüştürme görevinden alınan benzersiz tanımlayıcı (görev kimliği). Bu, dokulanacak temel 3B modeli sağlar. |
| `enable_original_uv` | BOOLEAN | Hayır | - | Etkinleştirildiğinde (varsayılan: `True`), düğüm yüklenen modelin orijinal UV düzenini kullanarak mevcut dokuları korur. Modelin orijinal UV'si yoksa, çıktı kalitesi daha düşük olabilir. |
| `pbr` | BOOLEAN | Hayır | - | Dokulu model için Fiziksel Tabanlı Renderlama (PBR) malzeme çıktısını etkinleştirir (varsayılan: `False`). |
| `text_style_prompt` | STRING | Hayır | - | Nesne için istenen doku stilinin metin açıklaması. Maksimum 600 karakter. `image_style` ile aynı anda kullanılamaz. |
| `image_style` | IMAGE | Hayır | - | Dokulama sürecine rehberlik etmesi için kullanılan 2B referans görseli. `text_style_prompt` ile aynı anda kullanılamaz. |

**Parametre Kısıtlamaları:**

* Ya bir `text_style_prompt` ya da bir `image_style` sağlamalısınız, ancak her ikisini aynı anda sağlayamazsınız.
* `text_style_prompt` maksimum 600 karakter ile sınırlıdır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Oluşturulan GLB modelinin dosya adı. Bu çıktı geriye dönük uyumluluk için sağlanmıştır. |
| `meshy_task_id` | MODEL_TASK_ID | Bu dokulama işi için benzersiz görev tanımlayıcısı. Sonucu referans almak için kullanılabilir. |
| `GLB` | FILE3DGLB | GLB dosya formatında kaydedilmiş dokulu 3B model. |
| `FBX` | FILE3DFBX | FBX dosya formatında kaydedilmiş dokulu 3B model. |
