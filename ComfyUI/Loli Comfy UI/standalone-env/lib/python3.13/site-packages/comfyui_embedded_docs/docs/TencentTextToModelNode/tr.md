> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentTextToModelNode/tr.md)

Bu düğüm, bir metin açıklamasından 3B model oluşturmak için Tencent'in Hunyuan3D Pro API'sini kullanır. Bir oluşturma görevi başlatmak için bir istek gönderir, sonucu sorgular ve GLB ile OBJ formatlarında nihai model dosyalarını indirir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"3.0"`<br>`"3.1"` | Kullanılacak Hunyuan3D modelinin sürümü. LowPoly seçeneği `3.1` modeli için kullanılamaz. |
| `prompt` | STRING | Evet | - | Oluşturulacak 3B modelin metin açıklaması. En fazla 1024 karakter desteklenir. |
| `face_count` | INT | Evet | 40000 - 1500000 | Oluşturulacak 3B model için hedef yüz sayısı. Varsayılan: 500000. |
| `generate_type` | DYNAMICCOMBO | Evet | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | Oluşturulacak 3B modelin türü. Mevcut seçenekler ve ilişkili parametreleri şunlardır:<br>- **Normal**: Standart bir model oluşturur. Bir `pbr` parametresi içerir (varsayılan: `False`).<br>- **LowPoly**: Düşük poligonlu bir model oluşturur. `polygon_type` (`"triangle"` veya `"quadrilateral"`) ve `pbr` (varsayılan: `False`) parametrelerini içerir.<br>- **Geometry**: Yalnızca geometri içeren bir model oluşturur. |
| `seed` | INT | Hayır | 0 - 2147483647 | Oluşturma için bir tohum değeri. Sonuçlar tohumdan bağımsız olarak belirleyici değildir. Yeni bir tohum ayarlamak, düğümün yeniden çalıştırılıp çalıştırılmayacağını kontrol eder. Varsayılan: 0. |

**Not:** `generate_type` parametresi dinamiktir. `"LowPoly"` seçmek, `polygon_type` ve `pbr` için ek girdileri görünür kılacaktır. `"Normal"` seçmek, `pbr` için bir girdiyi görünür kılacaktır. `"Geometry"` seçmek herhangi bir ek girdi göstermeyecektir.

**Kısıtlama:** `"LowPoly"` oluşturma türü, `"3.1"` modeli ile kullanılamaz.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Geriye dönük uyumluluk için eski bir çıktı. |
| `GLB` | FILE3DGLB | GLB dosya formatında oluşturulan 3B model. |
| `OBJ` | FILE3DOBJ | OBJ dosya formatında oluşturulan 3B model. |
