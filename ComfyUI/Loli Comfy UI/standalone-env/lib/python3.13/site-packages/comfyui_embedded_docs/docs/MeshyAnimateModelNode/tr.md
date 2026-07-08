> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyAnimateModelNode/tr.md)

Bu düğüm, Meshy hizmeti kullanılarak önceden iskeletlendirilmiş (rigged) bir 3B karakter modeline belirli bir animasyon uygular. Önceki bir iskeletlendirme işleminden alınan bir görev kimliği (task ID) ve kütüphaneden istenen animasyonu seçmek için bir eylem kimliği (action ID) alır. Düğüm daha sonra isteği işler ve animasyonlu modeli hem GLB hem de FBX dosya formatlarında döndürür.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `rig_task_id` | STRING | Evet | Yok | Daha önce tamamlanmış bir Meshy karakter iskeletlendirme işleminden alınan benzersiz görev kimliği. |
| `action_id` | INT | Evet | 0 - 696 | Uygulanacak animasyon eyleminin kimlik numarası. Mevcut değerlerin listesi için <https://docs.meshy.ai/en/api/animation-library> adresini ziyaret edin. (varsayılan: 0) |

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Animasyonlu model için bir dize tanımlayıcı. Bu çıkış yalnızca geriye dönük uyumluluk için sağlanmıştır. |
| `GLB` | FILE3DGLB | GLB formatındaki animasyonlu 3B model dosyası. |
| `FBX` | FILE3DFBX | FBX formatındaki animasyonlu 3B model dosyası. |
