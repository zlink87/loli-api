> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ViduExtendVideoNode/tr.md)

ViduExtendVideoNode, mevcut bir videonun uzunluğunu artırmak için ek kareler oluşturur. Kaynak video ve isteğe bağlı bir metin istemi temelinde kusursuz bir devamlılık oluşturmak için belirtilen bir AI modelini kullanır.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq2-pro"`<br>`"viduq2-turbo"` | Video uzatma için kullanılacak AI modeli. Bir model seçmek, onun özel süre ve çözünürlük ayarlarını görünür kılar. |
| `model.duration` | INT | Evet | 1 - 7 | Uzatılan videonun saniye cinsinden süresi (varsayılan: 4). Bu ayar bir model seçildikten sonra görünür. |
| `model.resolution` | COMBO | Evet | `"720p"`<br>`"1080p"` | Çıktı videosunun çözünürlüğü. Bu ayar bir model seçildikten sonra görünür. |
| `video` | VIDEO | Evet | - | Uzatılacak kaynak video. |
| `prompt` | STRING | Hayır | - | Uzatılan videonun içeriğini yönlendirmek için isteğe bağlı bir metin istemi (maksimum 2000 karakter, varsayılan: boş). |
| `seed` | INT | Hayır | 0 - 2147483647 | Üretimin rastgeleliğini kontrol etmek için bir seed değeri (varsayılan: 1). |
| `end_frame` | IMAGE | Hayır | - | Uzatma için hedef bitiş karesi olarak kullanılacak isteğe bağlı bir görüntü. Sağlanırsa, en-boy oranı 1:4 ile 4:1 arasında ve boyutları en az 128x128 piksel olmalıdır. |

**Not:** Kaynak `video` 4 ile 55 saniye arasında bir süreye sahip olmalıdır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Uzatılmış görüntüleri içeren yeni oluşturulan video dosyası. |
