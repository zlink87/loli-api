> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokVideoNode/tr.md)

Grok Video düğümü, bir metin açıklamasından kısa bir video oluşturur. Bir `prompt` kullanarak sıfırdan video oluşturabilir veya bir `prompt` temel alarak tek bir giriş görselini canlandırabilir. Düğüm, harici bir API'ye istek gönderir ve oluşturulan videoyu döndürür.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"grok-imagine-video-beta"` | Video oluşturma için kullanılacak model. |
| `prompt` | STRING | Evet | - | İstenilen videonun metin açıklaması. |
| `resolution` | COMBO | Evet | `"480p"`<br>`"720p"` | Çıktı videosunun çözünürlüğü. |
| `aspect_ratio` | COMBO | Evet | `"auto"`<br>`"16:9"`<br>`"4:3"`<br>`"3:2"`<br>`"1:1"`<br>`"2:3"`<br>`"3:4"`<br>`"9:16"` | Çıktı videosunun en-boy oranı. |
| `duration` | INT | Evet | 1 - 15 | Çıktı videosunun saniye cinsinden süresi (varsayılan: 6). |
| `seed` | INT | Evet | 0 - 2147483647 | Düğümün yeniden çalıştırılıp çalıştırılmayacağını belirlemek için kullanılan tohum; gerçek sonuçlar tohumdan bağımsız olarak belirleyici değildir (varsayılan: 0). |
| `image` | IMAGE | Hayır | - | Canlandırılacak isteğe bağlı bir giriş görseli. |

**Not:** Bir `image` sağlanırsa, yalnızca bir görsel desteklenir. Birden fazla görsel sağlamak hata oluşmasına neden olur.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Oluşturulan video. |
