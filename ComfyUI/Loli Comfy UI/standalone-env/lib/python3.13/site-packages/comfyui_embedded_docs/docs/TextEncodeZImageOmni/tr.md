> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeZImageOmni/tr.md)

TextEncodeZImageOmni düğümü, bir metin istemini ve isteğe bağlı referans görsellerini, görsel üretim modelleri için uygun bir koşullandırma formatına kodlayan gelişmiş bir koşullandırma düğümüdür. En fazla üç görseli işleyebilir, bunları isteğe bağlı olarak bir görsel kodlayıcı ve/veya bir VAE ile kodlayarak referans latents (gizli temsiller) üretebilir ve bu görsel referansları, belirli bir şablon yapısı kullanarak metin istemiyle bütünleştirir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Evet | | Metin istemini tokenize etmek ve kodlamak için kullanılan CLIP modeli. |
| `image_encoder` | CLIPVision | Hayır | | İsteğe bağlı bir görsel kodlayıcı model. Sağlandığında, giriş görsellerini kodlamak için kullanılacak ve ortaya çıkan gömme vektörleri (embedding) koşullandırmaya eklenecektir. |
| `prompt` | STRING | Evet | | Kodlanacak metin istemi. Bu alan çok satırlı giriş ve dinamik istemleri destekler. |
| `auto_resize_images` | BOOLEAN | Hayır | | Etkinleştirildiğinde (varsayılan: True), giriş görselleri VAE ile kodlanmadan önce piksel alanlarına göre otomatik olarak yeniden boyutlandırılacaktır. |
| `vae` | VAE | Hayır | | İsteğe bağlı bir VAE modeli. Sağlandığında, giriş görsellerini gizli temsillere (latent) kodlamak için kullanılacak ve bu temsiller referans latents olarak koşullandırmaya eklenecektir. |
| `image1` | IMAGE | Hayır | | Birinci isteğe bağlı referans görseli. |
| `image2` | IMAGE | Hayır | | İkinci isteğe bağlı referans görseli. |
| `image3` | IMAGE | Hayır | | Üçüncü isteğe bağlı referans görseli. |

**Not:** Düğüm en fazla üç görsel (`image1`, `image2`, `image3`) kabul edebilir. `image_encoder` ve `vae` girişleri yalnızca en az bir görsel sağlandığında kullanılır. `auto_resize_images` True ve bir `vae` bağlı olduğunda, görseller kodlanmadan önce toplam piksel alanı yaklaşık 1024x1024 olacak şekilde yeniden boyutlandırılır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | Kodlanmış metin istemini içeren ve görsel sağlandıysa kodlanmış görsel gömme vektörlerini ve/veya referans latents'ı içerebilen nihai koşullandırma çıktısı. |
