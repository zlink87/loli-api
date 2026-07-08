> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRefineNode/tr.md)

Meshy: Refine Draft Model düğümü, daha önce oluşturulmuş bir 3B taslak modeli alır ve kalitesini iyileştirir, isteğe bağlı olarak doku ekler. Meshy API'sine bir iyileştirme görevi gönderir ve işlem tamamlandığında nihai 3B model dosyalarını döndürür.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"latest"` | İyileştirme için kullanılacak AI modelini belirtir. Şu anda yalnızca "latest" (en son) model mevcuttur. |
| `meshy_task_id` | MESHY_TASK_ID | Evet | - | İyileştirmek istediğiniz taslak modelin benzersiz görev kimliği. |
| `enable_pbr` | BOOLEAN | Hayır | - | Temel renge ek olarak PBR Haritaları (metalik, pürüzlülük, normal) oluştur. Not: Heykel tarzı kullanılırken bu seçenek false olarak ayarlanmalıdır, çünkü Heykel tarzı kendi PBR harita setini oluşturur. (varsayılan: `False`) |
| `texture_prompt` | STRING | Hayır | - | Doku kaplama sürecine rehberlik etmesi için bir metin istemi sağlayın. Maksimum 600 karakter. Aynı anda 'texture_image' ile birlikte kullanılamaz. (varsayılan: boş dize) |
| `texture_image` | IMAGE | Hayır | - | Aynı anda yalnızca 'texture_image' veya 'texture_prompt' parametrelerinden biri kullanılabilir. (isteğe bağlı) |

**Not:** `texture_prompt` ve `texture_image` girdileri birbirini dışlar. Aynı işlem için hem bir metin istemi hem de doku kaplama için bir görsel sağlayamazsınız.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Oluşturulan GLB modelinin dosya adı. (Yalnızca geriye dönük uyumluluk için) |
| `meshy_task_id` | MESHY_TASK_ID | Gönderilen iyileştirme işi için benzersiz görev kimliği. |
| `GLB` | FILE3DGLB | GLB formatındaki nihai iyileştirilmiş 3B model. |
| `FBX` | FILE3DFBX | FBX formatındaki nihai iyileştirilmiş 3B model. |
