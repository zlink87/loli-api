> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2StartEndToVideoNode/tr.md)

Bu düğüm, sağlanan bir başlangıç karesi ile bir bitiş karesi arasında, bir metin istemi tarafından yönlendirilen bir enterpolasyon yaparak video oluşturur. Belirli bir Vidu modelini kullanarak iki görüntü arasında belirlenen bir süre boyunca pürüzsüz bir geçiş oluşturur.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | Video oluşturma için kullanılacak Vidu modeli. |
| `first_frame` | IMAGE | Evet | - | Video dizisi için başlangıç görüntüsü. Yalnızca tek bir görüntüye izin verilir. |
| `end_frame` | IMAGE | Evet | - | Video dizisi için bitiş görüntüsü. Yalnızca tek bir görüntüye izin verilir. |
| `prompt` | STRING | Evet | - | Video oluşturmayı yönlendiren bir metin açıklaması (maksimum 2000 karakter). |
| `duration` | INT | Hayır | 2 ila 8 | Oluşturulan videonun saniye cinsinden uzunluğu (varsayılan: 5). |
| `seed` | INT | Hayır | 0 ila 2147483647 | Tekrarlanabilir sonuçlar için rastgele oluşturmayı başlatmakta kullanılan bir sayı (varsayılan: 1). |
| `resolution` | COMBO | Hayır | `"720p"`<br>`"1080p"` | Oluşturulan videonun çıktı çözünürlüğü. |
| `movement_amplitude` | COMBO | Hayır | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | Kare içindeki nesnelerin hareket genliği. |

**Not:** `first_frame` ve `end_frame` görüntülerinin benzer en-boy oranlarına sahip olması gerekir. Düğüm, en-boy oranlarının 0.8 ila 1.25 arasında göreceli bir aralıkta olduğunu doğrulayacaktır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Oluşturulan video dosyası. |
