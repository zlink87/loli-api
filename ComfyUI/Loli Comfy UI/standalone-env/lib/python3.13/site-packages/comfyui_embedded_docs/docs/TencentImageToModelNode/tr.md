> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TencentImageToModelNode/tr.md)

Bu düğüm, bir veya daha fazla girdi görüntüsünden 3B model oluşturmak için Tencent'in Hunyuan3D Pro API'sini kullanır. Görüntüleri işler, API'ye gönderir ve oluşturulan 3B model dosyalarını GLB ve OBJ formatlarında döndürür.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"3.0"`<br>`"3.1"` | Kullanılacak Hunyuan3D modelinin sürümü. `3.1` modeli için LowPoly seçeneği mevcut değildir. |
| `image` | IMAGE | Evet | - | 3B modeli oluşturmak için kullanılan ana girdi görüntüsü. |
| `image_left` | IMAGE | Hayır | - | Çoklu görünüm oluşturma için nesnenin sol tarafının isteğe bağlı görüntüsü. |
| `image_right` | IMAGE | Hayır | - | Çoklu görünüm oluşturma için nesnenin sağ tarafının isteğe bağlı görüntüsü. |
| `image_back` | IMAGE | Hayır | - | Çoklu görünüm oluşturma için nesnenin arka tarafının isteğe bağlı görüntüsü. |
| `face_count` | INT | Evet | 40000 - 1500000 | Oluşturulan 3B model için hedef yüz sayısı (varsayılan: 500000). |
| `generate_type` | DYNAMICCOMBO | Evet | `"Normal"`<br>`"LowPoly"`<br>`"Geometry"` | Oluşturulacak 3B modelin türü. Bir seçenek seçmek, ilgili ek parametreleri görünür kılar. |
| `generate_type.pbr` | BOOLEAN | Hayır | - | Fiziksel Tabanlı Renderlama (PBR) malzeme oluşturmayı etkinleştirir. Bu parametre yalnızca `generate_type` "Normal" veya "LowPoly" olarak ayarlandığında görünür (varsayılan: False). |
| `generate_type.polygon_type` | COMBO | Hayır | `"triangle"`<br>`"quadrilateral"` | Mesh için kullanılacak poligon türü. Bu parametre yalnızca `generate_type` "LowPoly" olarak ayarlandığında görünür. |
| `seed` | INT | Evet | 0 - 2147483647 | Oluşturma işlemi için bir seed değeri. Seed, düğümün yeniden çalıştırılıp çalıştırılmayacağını kontrol eder; sonuçlar seed değerinden bağımsız olarak deterministik değildir (varsayılan: 0). |

**Not:** Tüm girdi görüntülerinin minimum genişlik ve yüksekliği 128 piksel olmalıdır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Geriye dönük uyumluluk için eski bir çıktı. |
| `GLB` | FILE3DGLB | GLB (Binary GL Transmission Format) dosya formatında oluşturulan 3B model. |
| `OBJ` | FILE3DOBJ | OBJ (Wavefront) dosya formatında oluşturulan 3B model. |
