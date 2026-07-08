> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3ImageToVideoNode/tr.md)

Vidu Q3 Görüntüden-Videoya Üretim düğümü, bir giriş görüntüsünden başlayarak bir video dizisi oluşturur. Görüntüyü canlandırmak için Vidu Q3 Pro modelini kullanır, isteğe bağlı olarak bir metin istemiyle yönlendirilir ve bir video dosyası çıktısı verir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq3-pro"` | Video üretimi için kullanılacak model. |
| `model.resolution` | COMBO | Evet | `"720p"`<br>`"1080p"`<br>`"2K"` | Çıktı videosunun çözünürlüğü. |
| `model.duration` | INT | Evet | 1 ila 16 | Çıktı videosunun saniye cinsinden süresi (varsayılan: 5). |
| `model.audio` | BOOLEAN | Evet | `True` / `False` | Etkinleştirildiğinde, sesli (diyalog ve ses efektleri dahil) video çıktısı verir (varsayılan: False). |
| `image` | IMAGE | Evet | - | Oluşturulan videonun başlangıç karesi olarak kullanılacak bir görüntü. |
| `prompt` | STRING | Hayır | - | Video üretimi için isteğe bağlı bir metin istemi (maksimum 2000 karakter) (varsayılan: boş). |
| `seed` | INT | Hayır | 0 ila 2147483647 | Üretimin rastgeleliğini kontrol etmek için bir tohum değeri (varsayılan: 1). |

**Not:** `image` parametresinin en-boy oranı 1:4 ile 4:1 (dikeyden yataya) arasında olmalıdır. `prompt` parametresi isteğe bağlıdır ancak 2000 karakteri aşamaz.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Oluşturulan video dosyası. |
