> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/VAEDecodeAudioTiled/tr.md)

Bu düğüm, sıkıştırılmış bir ses temsilini (latent örnekleri), bir Varyasyonel Otokodlayıcı (VAE) kullanarak bir ses dalga formuna dönüştürür. Verileri, bellek kullanımını yönetmek için daha küçük, üst üste binen bölümler (dilimler) halinde işler, bu da daha uzun ses dizilerini işlemek için uygun hale getirir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `samples` | LATENT | Evet | Yok | Çözülecek sesin sıkıştırılmış latent temsili. |
| `vae` | VAE | Evet | Yok | Çözme işlemini gerçekleştirmek için kullanılan Varyasyonel Otokodlayıcı modeli. |
| `tile_size` | INT | Hayır | 32 - 8192 | Her bir işleme diliminin boyutu. Ses, bellekten tasarruf etmek için bu uzunluktaki bölümler halinde çözülür (varsayılan: 512). |
| `overlap` | INT | Hayır | 0 - 1024 | Bitişik dilimlerin üst üste bindiği örnek sayısı. Bu, dilimler arasındaki sınırlarda oluşabilecek yapay bozulmaları azaltmaya yardımcı olur (varsayılan: 64). |

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | AUDIO | Çözülmüş ses dalga formu. |
