> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerPreciseV2Node/tr.md)

Magnific Image Upscale (Precise V2) düğümü, keskinlik, gren ve detay geliştirme üzerinde hassas kontrol sağlayarak yüksek kalitede görüntü büyütme işlemi gerçekleştirir. Görüntüleri harici bir API üzerinden işler ve maksimum 10060×10060 piksel çıktı çözünürlüğünü destekler. Düğüm, farklı işleme stilleri sunar ve talep edilen çıktı boyutu izin verilen maksimum boyutu aşacaksa giriş görüntüsünü otomatik olarak küçültebilir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Evet | - | Büyütülecek giriş görüntüsü. Tam olarak bir görüntü gereklidir. Minimum boyutlar 160x160 pikseldir. En-boy oranı 1:3 ile 3:1 arasında olmalıdır. |
| `scale_factor` | STRING | Evet | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | İstenen büyütme çarpanı. |
| `flavor` | STRING | Evet | `"sublime"`<br>`"photo"`<br>`"photo_denoiser"` | İşleme stili. "sublime" genel kullanım içindir, "photo" fotoğraflar için optimize edilmiştir ve "photo_denoiser" gürültülü fotoğraflar içindir. |
| `sharpen` | INT | Hayır | 0 - 100 | Kenar tanımlamasını ve netliği artırmak için görüntü keskinleştirme yoğunluğunu kontrol eder. Daha yüksek değerler daha keskin bir sonuç üretir. Varsayılan: 7. |
| `smart_grain` | INT | Hayır | 0 - 100 | Büyütülmüş görüntünün çok düz veya yapay görünmesini önlemek için akıllı gren veya doku geliştirme ekler. Varsayılan: 7. |
| `ultra_detail` | INT | Hayır | 0 - 100 | Büyütme işlemi sırasında eklenen ince detay, doku ve mikro-detay miktarını kontrol eder. Varsayılan: 30. |
| `auto_downscale` | BOOLEAN | Hayır | - | Etkinleştirildiğinde, hesaplanan çıktı boyutları izin verilen maksimum 10060x10060 piksel çözünürlüğü aşacaksa, düğüm giriş görüntüsünü otomatik olarak küçültecektir. Bu, hataları önlemeye yardımcı olur ancak kaliteyi etkileyebilir. Varsayılan: False. |

**Not:** Eğer `auto_downscale` devre dışı bırakılmışsa ve talep edilen çıktı boyutu (giriş boyutları × `scale_factor`) 10060x10060 pikseli aşarsa, düğüm bir hata verecektir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Elde edilen büyütülmüş görüntü. |
