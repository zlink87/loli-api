> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2TextToVideoNode/tr.md)

Vidu2 Metinden Videoya Üretim düğümü, bir metin açıklamasından video oluşturur. İsteğinize dayalı video içeriği üretmek için harici bir API'ye bağlanır ve videonun uzunluğu, görsel stili ve formatı üzerinde kontrol sağlar.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq2"` | Video üretimi için kullanılacak AI modeli. Şu anda yalnızca bir model mevcuttur. |
| `prompt` | STRING | Evet | - | Video üretimi için metinsel açıklama, maksimum 2000 karakter uzunluğunda. |
| `duration` | INT | Hayır | 1 ila 10 | Üretilen videonun saniye cinsinden uzunluğu. Değer bir sürgü kullanılarak ayarlanabilir (varsayılan: 5). |
| `seed` | INT | Hayır | 0 ila 2147483647 | Üretimin rastgeleliğini kontrol etmek ve tekrarlanabilir sonuçlar elde etmek için kullanılan bir sayı. Üretim sonrasında kontrol edilebilir (varsayılan: 1). |
| `aspect_ratio` | COMBO | Hayır | `"16:9"`<br>`"9:16"`<br>`"3:4"`<br>`"4:3"`<br>`"1:1"` | Videonun genişliği ve yüksekliği arasındaki oransal ilişki. |
| `resolution` | COMBO | Hayır | `"720p"`<br>`"1080p"` | Üretilen videonun piksel boyutları. |
| `background_music` | BOOLEAN | Hayır | - | Üretilen videoya arka plan müziği eklenip eklenmeyeceği (varsayılan: False). |

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Üretilen video dosyası. |
