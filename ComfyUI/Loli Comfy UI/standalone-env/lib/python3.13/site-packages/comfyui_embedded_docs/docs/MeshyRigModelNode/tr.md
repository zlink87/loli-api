> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyRigModelNode/tr.md)

Meshy: Rig Model düğümü, Meshy'den bir 3B model görevi alır ve iskeletlendirilmiş bir karakter modeli oluşturur. Model için otomatik olarak bir iskelet oluşturur, böylece model pozlanabilir ve canlandırılabilir. Düğüm, iskeletlendirilmiş modeli hem GLB hem de FBX dosya formatlarında çıktı olarak verir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `meshy_task_id` | STRING | Evet | Yok | İskeletlendirilecek modeli oluşturan önceki bir Meshy işleminin (örneğin, metinden-3B'ye veya görüntüden-3B'ye) benzersiz görev kimliği. |
| `height_meters` | FLOAT | Evet | 0.1 - 15.0 | Karakter modelinin metre cinsinden yaklaşık yüksekliği. Bu, ölçeklendirme ve iskeletlendirme doğruluğuna yardımcı olur (varsayılan: 1.7). |
| `texture_image` | IMAGE | Hayır | Yok | Modelin UV açılmış temel renk doku görüntüsü. |

**Not:** Otomatik iskeletlendirme işlemi şu anda doku kaplanmamış ağlar, insansı olmayan varlıklar veya uzuv ve vücut yapısı belirsiz insansı varlıklar için uygun değildir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Geriye dönük uyumluluk için eski bir çıktı, GLB modelinin dosya adını içerir. |
| `rig_task_id` | STRING | Bu iskeletlendirme işlemi için benzersiz görev kimliği, sonucu referans almak için kullanılabilir. |
| `GLB` | FILE3DGLB | GLB dosya formatında kaydedilmiş, iskeletlendirilmiş 3B karakter modeli. |
| `FBX` | FILE3DFBX | FBX dosya formatında kaydedilmiş, iskeletlendirilmiş 3B karakter modeli. |
