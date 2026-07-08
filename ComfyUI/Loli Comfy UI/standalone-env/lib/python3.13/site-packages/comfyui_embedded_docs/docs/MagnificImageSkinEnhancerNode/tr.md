> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageSkinEnhancerNode/tr.md)

Magnific Image Skin Enhancer düğümü, portre görüntülerine cilt görünümünü iyileştirmek için özel AI işleme uygular. Sanatsal efektler için yaratıcı, orijinal görünümü korumak için sadık ve aydınlatma veya gerçekçilik gibi hedeflenen iyileştirmeler için esnek olmak üzere farklı geliştirme hedefleri için üç ayrı mod sunar. Düğüm, işleme için görüntüyü harici bir API'ye yükler ve geliştirilmiş sonucu döndürür.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Evet | - | Geliştirilecek portre görüntüsü. |
| `sharpen` | INT | Hayır | 0 ila 100 | Keskinleştirme yoğunluk seviyesi (varsayılan: 0). |
| `smart_grain` | INT | Hayır | 0 ila 100 | Akıllı gren yoğunluk seviyesi (varsayılan: 2). |
| `mode` | COMBO | Evet | `"creative"`<br>`"faithful"`<br>`"flexible"` | Kullanılacak işleme modu. `"creative"` sanatsal geliştirme, `"faithful"` orijinal görünümü koruma ve `"flexible"` hedeflenen optimizasyon içindir. |
| `skin_detail` | INT | Hayır | 0 ila 100 | Cilt detayı geliştirme seviyesi. Bu giriş yalnızca `mode` `"faithful"` olarak ayarlandığında mevcuttur ve gereklidir (varsayılan: 80). |
| `optimized_for` | COMBO | Hayır | `"enhance_skin"`<br>`"improve_lighting"`<br>`"enhance_everything"`<br>`"transform_to_real"`<br>`"no_make_up"` | Geliştirme optimizasyon hedefi. Bu giriş yalnızca `mode` `"flexible"` olarak ayarlandığında mevcuttur ve gereklidir. |

**Kısıtlamalar:**

* Düğüm tam olarak bir giriş görüntüsü kabul eder.
* Giriş görüntüsünün minimum yükseklik ve genişliği 160 piksel olmalıdır.
* `skin_detail` parametresi yalnızca `mode` `"faithful"` olarak ayarlandığında etkindir.
* `optimized_for` parametresi yalnızca `mode` `"flexible"` olarak ayarlandığında etkindir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Geliştirilmiş portre görüntüsü. |
