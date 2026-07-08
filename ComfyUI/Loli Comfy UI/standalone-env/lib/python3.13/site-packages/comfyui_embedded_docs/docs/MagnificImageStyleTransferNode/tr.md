> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageStyleTransferNode/tr.md)

Bu düğüm, bir referans görselden alınan görsel stili giriş görselinize uygular. Görselleri işlemek için harici bir AI servisi kullanır ve stil transferinin gücünü ile orijinal görselin yapısının korunmasını kontrol etmenize olanak tanır.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Evet | - | Stil transferi uygulanacak görsel. |
| `reference_image` | IMAGE | Evet | - | Stilin çıkarılacağı referans görsel. |
| `prompt` | STRING | Hayır | - | Stil transferini yönlendirmek için isteğe bağlı bir metin ipucu. |
| `style_strength` | INT | Hayır | 0 ila 100 | Stil gücü yüzdesi (varsayılan: 100). |
| `structure_strength` | INT | Hayır | 0 ila 100 | Orijinal görselin yapısını korur (varsayılan: 50). |
| `flavor` | COMBO | Hayır | "faithful"<br>"gen_z"<br>"psychedelia"<br>"detaily"<br>"clear"<br>"donotstyle"<br>"donotstyle_sharp" | Stil transferi çeşidi. |
| `engine` | COMBO | Hayır | "balanced"<br>"definio"<br>"illusio"<br>"3d_cartoon"<br>"colorful_anime"<br>"caricature"<br>"real"<br>"super_real"<br>"softy" | İşleme motoru seçimi. |
| `portrait_mode` | COMBO | Hayır | "disabled"<br>"enabled" | Yüz geliştirmeleri için portre modunu etkinleştir. |
| `portrait_style` | COMBO | Hayır | "standard"<br>"pop"<br>"super_pop" | Portre görsellere uygulanan görsel stil. Bu giriş yalnızca `portrait_mode` "enabled" olarak ayarlandığında kullanılabilir. |
| `portrait_beautifier` | COMBO | Hayır | "none"<br>"beautify_face"<br>"beautify_face_max" | Portrelerdeki yüz güzelleştirme yoğunluğu. Bu giriş yalnızca `portrait_mode` "enabled" olarak ayarlandığında kullanılabilir. |
| `fixed_generation` | BOOLEAN | Hayır | - | Devre dışı bırakıldığında, her üretimin bir dereceye kadar rastgelelik getirmesi ve daha çeşitli sonuçlara yol açması beklenir (varsayılan: True). |

**Kısıtlamalar:**

* Tam olarak bir `image` ve bir `reference_image` gereklidir.
* Her iki görselin en boy oranı 1:3 ile 3:1 arasında olmalıdır.
* Her iki görselin minimum yüksekliği ve genişliği 160 piksel olmalıdır.
* `portrait_style` ve `portrait_beautifier` parametreleri yalnızca `portrait_mode` "enabled" olarak ayarlandığında etkin ve gerekli hale gelir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Stil transferi uygulandıktan sonra elde edilen görsel. |
