> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu3TextToVideoNode/tr.md)

Vidu Q3 Metinden Videoya Üretim düğümü, bir metin açıklamasından video oluşturur. Vidu Q3 Pro modelini kullanarak, videonun uzunluğu, çözünürlüğü ve en-boy oranını kontrol etmenize olanak tanıyan, verdiğiniz isteme dayalı video içeriği üretir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq3-pro"` | Video üretimi için kullanılacak model. Bu seçeneği belirlemek, en-boy oranı, çözünürlük, süre ve ses için ek yapılandırma parametrelerini görünür kılar. |
| `model.aspect_ratio` | COMBO | Evet* | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | Çıktı videosunun en-boy oranı. Bu parametre, `model` seçildiğinde görünür hale gelir. |
| `model.resolution` | COMBO | Evet* | `"720p"`<br>`"1080p"` | Çıktı videosunun çözünürlüğü. Bu parametre, `model` seçildiğinde görünür hale gelir. |
| `model.duration` | INT | Evet* | 1 - 16 | Çıktı videosunun saniye cinsinden süresi (varsayılan: 5). Bu parametre, `model` seçildiğinde görünür hale gelir. |
| `model.audio` | BOOLEAN | Evet* | Doğru/Yanlış | Etkinleştirildiğinde, sesli (diyalog ve ses efektleri dahil) video çıktısı verir (varsayılan: Yanlış). Bu parametre, `model` seçildiğinde görünür hale gelir. |
| `prompt` | STRING | Evet | Yok | Video üretimi için metinsel açıklama, maksimum 2000 karakter uzunluğunda. |
| `seed` | INT | Hayır | 0 - 2147483647 | Üretimin rastgeleliğini kontrol etmek için bir tohum değeri (varsayılan: 1). |

*Not: `aspect_ratio`, `resolution`, `duration` ve `audio` parametreleri, `model` seçildikten sonra zorunlu hale gelir, çünkü bunlar model yapılandırmasının bir parçasıdır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `video` | VIDEO | Üretilen video dosyası. |
