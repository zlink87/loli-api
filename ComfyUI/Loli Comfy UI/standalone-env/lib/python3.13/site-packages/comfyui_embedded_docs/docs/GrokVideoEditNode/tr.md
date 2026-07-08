> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokVideoEditNode/tr.md)

Bu düğüm, mevcut bir videoyu metin tabanlı bir isteme göre düzenlemek için Grok API'sini kullanır. Videoyu yükler, AI modeline isteğinizi gönderir ve yeni oluşturulan videoyu döndürür.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"grok-imagine-video-beta"` | Video düzenleme için kullanılacak AI modeli. |
| `prompt` | STRING | Evet | N/A | İstenilen videonun metin açıklaması. |
| `video` | VIDEO | Evet | N/A | Düzenlenecek giriş videosu. Desteklenen maksimum süre 8.7 saniye ve maksimum dosya boyutu 50MB'dır. |
| `seed` | INT | Hayır | 0 ile 2147483647 arası | Düğümün yeniden çalıştırılıp çalıştırılmayacağını belirlemek için bir başlangıç değeri. Gerçek sonuçlar, başlangıç değerinden bağımsız olarak belirleyici değildir (varsayılan: 0). |

**Kısıtlamalar:**

* Giriş `video` süresi 1 ile 8.7 saniye arasında olmalıdır.
* Giriş `video` dosya boyutu 50MB'ı geçmemelidir.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `video` | VIDEO | AI modeli tarafından oluşturulan düzenlenmiş video. |
