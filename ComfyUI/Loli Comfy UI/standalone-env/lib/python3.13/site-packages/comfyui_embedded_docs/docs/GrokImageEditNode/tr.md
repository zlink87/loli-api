> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageEditNode/tr.md)

Grok Image Edit düğümü, mevcut bir görseli bir metin istemine dayanarak düzenler. Girdinizin varyasyonları olan bir veya daha fazla yeni görsel oluşturmak için Grok API'sini kullanır ve bu süreç açıklamanız tarafından yönlendirilir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"grok-imagine-image-beta"` | Görsel düzenleme için kullanılacak belirli yapay zeka modeli. |
| `image` | IMAGE | Evet | | Düzenlenecek girdi görseli. Yalnızca bir görsel desteklenir. |
| `prompt` | STRING | Evet | | Düzenlenmiş görseli oluşturmak için kullanılan metin istemi. |
| `resolution` | COMBO | Evet | `"1K"` | Çıktı görseli için çözünürlük. |
| `number_of_images` | INT | Hayır | 1 - 10 | Oluşturulacak düzenlenmiş görsel sayısı (varsayılan: 1). |
| `seed` | INT | Hayır | 0 - 2147483647 | Düğümün yeniden çalıştırılıp çalıştırılmayacağını belirleyen tohum değeri; gerçek sonuçlar tohum değerinden bağımsız olarak belirleyici değildir (varsayılan: 0). |

**Not:** `image` girdisi tam olarak bir görsel içermelidir. Birden fazla görsel sağlamak bir hataya neden olacaktır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | IMAGE | Düğüm tarafından oluşturulan düzenlenmiş görsel(ler). Eğer `number_of_images` 1'den büyükse, çıktılar bir toplu iş halinde birleştirilir. |
