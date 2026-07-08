> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyMultiImageToModelNode/tr.md)

Bu düğüm, birden fazla girdi görselinden 3B model oluşturmak için Meshy API'sini kullanır. Sağlanan görselleri yükler, bir işleme görevi başlatır ve sonuçta oluşan 3B model dosyalarını (GLB ve FBX) referans için görev kimliğiyle birlikte döndürür.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
| :--- | :--- | :--- | :--- | :--- |
| `model` | COMBO | Evet | `"latest"` | Kullanılacak yapay zeka modeli sürümünü belirtir. |
| `images` | IMAGE | Evet | 2 ila 4 görsel | 3B model oluşturmak için kullanılan bir dizi görsel. 2 ile 4 arasında görsel sağlamanız gerekir. |
| `should_remesh` | COMBO | Evet | `"true"`<br>`"false"` | Oluşturulan ağın işlenip işlenmeyeceğini belirler. `"false"` olarak ayarlandığında, düğüm işlenmemiş üçgen bir ağ döndürür. |
| `topology` | COMBO | Hayır | `"triangle"`<br>`"quad"` | Yeniden ağ yapılandırılmış çıktı için hedef çokgen türü. Bu parametre yalnızca `should_remesh` `"true"` olarak ayarlandığında kullanılabilir ve gereklidir. |
| `target_polycount` | INT | Hayır | 100 ila 300000 | Yeniden ağ yapılandırılmış model için hedef çokgen sayısı (varsayılan: 300000). Bu parametre yalnızca `should_remesh` `"true"` olarak ayarlandığında kullanılabilir. |
| `symmetry_mode` | COMBO | Evet | `"auto"`<br>`"on"`<br>`"off"` | Oluşturulan modele simetri uygulanıp uygulanmayacağını kontrol eder. |
| `should_texture` | COMBO | Evet | `"true"`<br>`"false"` | Doku oluşturulup oluşturulmayacağını belirler. `"false"` olarak ayarlanması, doku aşamasını atlar ve dokusuz bir ağ döndürür. |
| `enable_pbr` | BOOLEAN | Hayır | `True` / `False` | `should_texture` `"true"` olduğunda, bu seçenek temel renge ek olarak PBR Haritaları (metalik, pürüzlülük, normal) oluşturur (varsayılan: `False`). |
| `texture_prompt` | STRING | Hayır | - | Doku işlemini yönlendirmek için bir metin istemi (maksimum 600 karakter). `texture_image` ile aynı anda kullanılamaz. Bu parametre yalnızca `should_texture` `"true"` olarak ayarlandığında kullanılabilir. |
| `texture_image` | IMAGE | Hayır | - | Doku işlemini yönlendirmek için bir görsel. Aynı anda yalnızca `texture_image` veya `texture_prompt` kullanılabilir. Bu parametre yalnızca `should_texture` `"true"` olarak ayarlandığında kullanılabilir. |
| `pose_mode` | COMBO | Evet | `""`<br>`"A-pose"`<br>`"T-pose"` | Oluşturulan model için poz modunu belirtir. |
| `seed` | INT | Evet | 0 ila 2147483647 | Oluşturma işlemi için bir tohum değeri (varsayılan: 0). Sonuçlar tohumdan bağımsız olarak belirleyici değildir, ancak tohumu değiştirmek düğümün yeniden çalıştırılmasını tetikleyebilir. |

**Parametre Kısıtlamaları:**

* `images` girdisi için 2 ile 4 arasında görsel sağlamanız gerekir.
* `topology` ve `target_polycount` parametreleri yalnızca `should_remesh` `"true"` olarak ayarlandığında etkindir.
* `enable_pbr`, `texture_prompt` ve `texture_image` parametreleri yalnızca `should_texture` `"true"` olarak ayarlandığında etkindir.
* `texture_prompt` ve `texture_image` aynı anda kullanılamaz; birbirini dışlayan seçeneklerdir.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
| :--- | :--- | :--- |
| `model_file` | STRING | Oluşturulan GLB modelinin dosya adı. Bu çıktı geriye dönük uyumluluk için sağlanmıştır. |
| `meshy_task_id` | MESHY_TASK_ID | Meshy API görevi için benzersiz tanımlayıcı. |
| `GLB` | FILE3DGLB | GLB formatında oluşturulan 3B model. |
| `FBX` | FILE3DFBX | FBX formatında oluşturulan 3B model. |
