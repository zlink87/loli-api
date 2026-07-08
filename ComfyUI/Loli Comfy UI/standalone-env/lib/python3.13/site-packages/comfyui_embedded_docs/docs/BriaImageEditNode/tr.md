> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/BriaImageEditNode/tr.md)

Bria FIBO Görüntü Düzenleme düğümü, mevcut bir görüntüyü bir metin talimatı kullanarak değiştirmenize olanak tanır. Görüntüyü ve isteminizi Bria API'sine gönderir; API, isteğinize dayanarak görüntünün yeni, düzenlenmiş bir versiyonunu oluşturmak için FIBO modelini kullanır. Ayrıca, düzenlemeleri belirli bir alanla sınırlamak için bir maske sağlayabilirsiniz.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"FIBO"` | Görüntü düzenleme için kullanılacak model versiyonu. |
| `image` | IMAGE | Evet | - | Düzenlemek istediğiniz girdi görüntüsü. |
| `prompt` | STRING | Hayır | - | Görüntünün nasıl düzenleneceğini açıklayan metin talimatı (varsayılan: boş). |
| `negative_prompt` | STRING | Hayır | - | Düzenlenmiş görüntüde görünmesini istemediklerinizi açıklayan metin (varsayılan: boş). |
| `structured_prompt` | STRING | Hayır | - | Yapılandırılmış düzenleme istemini JSON formatında içeren bir dize. Hassas, programatik kontrol için normal `prompt` yerine bunu kullanın (varsayılan: boş). |
| `seed` | INT | Evet | 1 - 2147483647 | Rastgele oluşturmayı başlatmak için kullanılan, tekrarlanabilir sonuçlar sağlayan bir sayı (varsayılan: 1). |
| `guidance_scale` | FLOAT | Evet | 3.0 - 5.0 | Oluşturulan görüntünün istemi ne kadar yakından takip edeceğini kontrol eder. Daha yüksek bir değer, daha güçlü bir bağlılık sağlar (varsayılan: 3.0). |
| `steps` | INT | Evet | 20 - 50 | Modelin gerçekleştireceği gürültü giderme adım sayısı (varsayılan: 50). |
| `moderation` | DYNAMICCOMBO | Evet | `"true"`<br>`"false"` | İçerik moderasyonunu etkinleştirir veya devre dışı bırakır. `"true"` seçmek ek moderasyon seçeneklerini görünür kılar. |
| `mask` | MASK | Hayır | - | İsteğe bağlı bir maske görüntüsü. Sağlanırsa, düzenlemeler yalnızca görüntünün maskelenmiş alanlarına uygulanır. |

**Önemli Kısıtlamalar:**

* `prompt` veya `structured_prompt` girdilerinden en az birini sağlamalısınız. İkisi de boş olamaz.
* Tam olarak bir `image` girdisi gereklidir.
* `moderation` parametresi `"true"` olarak ayarlandığında, üç ek boole girdisi kullanılabilir hale gelir: `prompt_content_moderation`, `visual_input_moderation` ve `visual_output_moderation`.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `IMAGE` | IMAGE | Bria API'si tarafından döndürülen düzenlenmiş görüntü. |
| `structured_prompt` | STRING | Düzenleme işlemi sırasında kullanılan veya oluşturulan yapılandırılmış istem. |
