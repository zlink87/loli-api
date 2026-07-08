> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawVideoEnhance/tr.md)

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | DYNAMIC COMBO | Evet | Birden fazla seçenek mevcut | Video iyileştirme için kullanılacak AI modeli. Bir model seçmek, iç içe bir `resolution` parametresini görünür kılar. |
| `model.resolution` | COMBO | Evet | `"original"`<br>`"720p"`<br>`"1080p"`<br>`"2k/qhd"`<br>`"4k/uhd"`<br>`"8k"` | İyileştirilmiş video için hedef çözünürlük. Bazı seçenekler, seçilen `model`'e bağlı olarak kullanılamayabilir. |
| `video` | VIDEO | Evet | Yok | İyileştirilecek giriş video dosyası. |

**Kısıtlamalar:**

* Giriş `video` dosyasının süresi 0.5 saniye ile 60 dakika (3600 saniye) arasında olmalıdır.
* Seçilen `resolution`, giriş videosunun boyutlarından büyük olmalıdır. Video kare ise, seçilen çözünürlük genişlik/yükseklik değerinden büyük olmalıdır. Kare olmayan videolarda, seçilen çözünürlük videonun daha kısa olan boyutundan büyük olmalıdır. Hedef çözünürlük daha küçükse bir hata oluşur. Giriş videosunun çözünürlüğünü korumak için `"original"` seçeneğini belirleyin.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `video` | VIDEO | İyileştirilmiş video dosyası. |
