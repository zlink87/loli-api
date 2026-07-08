> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MeshyImageToModelNode/tr.md)

Meshy: Image to Model düğümü, tek bir giriş görüntüsünden 3B model oluşturmak için Meshy API'sini kullanır. Görüntünüzü yükler, bir işleme görevi gönderir ve oluşturulan 3B model dosyalarını (GLB ve FBX) ile referans için görev kimliğini döndürür.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"latest"` | Oluşturma için kullanılacak AI model sürümünü belirtir. |
| `image` | IMAGE | Evet | - | 3B modele dönüştürülecek giriş görüntüsü. |
| `should_remesh` | DYNAMIC COMBO | Evet | `"true"`<br>`"false"` | Oluşturulan ağın işlenip işlenmeyeceğini belirler. `"false"` olarak ayarlandığında, düğüm işlenmemiş üçgen bir ağ döndürür. |
| `topology` | COMBO | Hayır* | `"triangle"`<br>`"quad"` | Yeniden ağ yapılandırılmış model için hedef çokgen topolojisi. Bu giriş yalnızca `should_remesh` `"true"` olarak ayarlandığında mevcuttur ve gereklidir. |
| `target_polycount` | INT | Hayır* | 100 - 300000 | Yeniden ağ yapılandırılmış model için hedef çokgen sayısı. Bu giriş yalnızca `should_remesh` `"true"` olarak ayarlandığında mevcuttur ve gereklidir. Varsayılan değer 300000'dir. |
| `symmetry_mode` | COMBO | Evet | `"auto"`<br>`"on"`<br>`"off"` | Oluşturulan 3B modele uygulanan simetriyi kontrol eder. |
| `should_texture` | DYNAMIC COMBO | Evet | `"true"`<br>`"false"` | Model için doku oluşturulup oluşturulmayacağını belirler. `"false"` olarak ayarlamak, doku aşamasını atlar ve dokusuz bir ağ döndürür. |
| `enable_pbr` | BOOLEAN | Hayır* | - | `should_texture` `"true"` olduğunda, bu seçenek temel renge ek olarak PBR haritaları (metalik, pürüzlülük, normal) oluşturur. Varsayılan değer `False`'dır. |
| `texture_prompt` | STRING | Hayır* | - | Doku işlemini yönlendirmek için bir metin istemi (maksimum 600 karakter). Bu giriş yalnızca `should_texture` `"true"` olduğunda mevcuttur. `texture_image` ile aynı anda kullanılamaz. |
| `texture_image` | IMAGE | Hayır* | - | Doku işlemini yönlendirmek için bir görüntü. Bu giriş yalnızca `should_texture` `"true"` olduğunda mevcuttur. `texture_prompt` ile aynı anda kullanılamaz. |
| `pose_mode` | COMBO | Evet | `""`<br>`"A-pose"`<br>`"T-pose"` | Oluşturulan model için poz modunu belirtir. |
| `seed` | INT | Evet | 0 - 2147483647 | Oluşturma işlemi için bir tohum değeri. Sonuçlar, tohum değerinden bağımsız olarak deterministik değildir. Varsayılan değer 0'dır. |

**Parametre Kısıtlamaları Hakkında Not:**

* `topology` ve `target_polycount` girişleri yalnızca `should_remesh` `"true"` olarak ayarlandığında gereklidir.
* `enable_pbr`, `texture_prompt` ve `texture_image` girişleri yalnızca `should_texture` `"true"` olarak ayarlandığında mevcuttur.
* `texture_prompt` ve `texture_image` aynı anda kullanılamaz. Eğer `should_texture` `"true"` iken her ikisi de sağlanırsa, düğüm bir hata verecektir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model_file` | STRING | Oluşturulan GLB modelinin dosya adı. (Geriye dönük uyumluluk için korunmuştur). |
| `meshy_task_id` | MESHY_TASK_ID | Referans veya sorun giderme için kullanılabilecek Meshy API görevinin benzersiz tanımlayıcısı. |
| `GLB` | FILE3DGLB | GLB dosya formatında oluşturulan 3B model. |
| `FBX` | FILE3DFBX | FBX dosya formatında oluşturulan 3B model. |
