> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageUpscalerCreativeNode/tr.md)

Bu düğüm, bir görüntüyü büyütmek ve yaratıcı bir şekilde geliştirmek için Magnific AI hizmetini kullanır. Geliştirme sürecini bir metin istemiyle yönlendirmenize, optimize edilecek belirli bir stil seçmenize ve detay, orijinale benzerlik, stilizasyon gücü gibi yaratıcı sürecin çeşitli yönlerini kontrol etmenize olanak tanır. Düğüm, seçtiğiniz faktörde (2x, 4x, 8x veya 16x) ve maksimum 25,3 megapiksel çıktı boyutunda büyütülmüş bir görüntü üretir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Evet | - | Büyütülecek ve geliştirilecek giriş görüntüsü. |
| `prompt` | STRING | Hayır | - | Görüntünün yaratıcı geliştirmesini yönlendirmek için bir metin açıklaması. Bu isteğe bağlıdır (varsayılan: boş). |
| `scale_factor` | COMBO | Evet | `"2x"`<br>`"4x"`<br>`"8x"`<br>`"16x"` | Görüntü boyutlarının büyütüleceği faktör. |
| `optimized_for` | COMBO | Evet | `"standard"`<br>`"soft_portraits"`<br>`"hard_portraits"`<br>`"art_n_illustration"`<br>`"videogame_assets"`<br>`"nature_n_landscapes"`<br>`"films_n_photography"`<br>`"3d_renders"`<br>`"science_fiction_n_horror"` | Geliştirme sürecinin optimize edileceği stil veya içerik türü. |
| `creativity` | INT | Hayır | -10 - 10 | Görüntüye uygulanan yaratıcı yorumlama seviyesini kontrol eder (varsayılan: 0). |
| `hdr` | INT | Hayır | -10 - 10 | Tanım ve detay seviyesi (varsayılan: 0). |
| `resemblance` | INT | Hayır | -10 - 10 | Orijinal görüntüye benzerlik seviyesi (varsayılan: 0). |
| `fractality` | INT | Hayır | -10 - 10 | İstemin gücü ve piksel başına karmaşıklık (varsayılan: 0). |
| `engine` | COMBO | Evet | `"automatic"`<br>`"magnific_illusio"`<br>`"magnific_sharpy"`<br>`"magnific_sparkle"` | İşleme için kullanılacak belirli AI motoru. |
| `auto_downscale` | BOOLEAN | Hayır | - | Etkinleştirildiğinde, talep edilen büyütme işlemi izin verilen maksimum 25,3 megapiksel çıktı boyutunu aşacaksa, düğüm giriş görüntüsünü otomatik olarak küçültecektir (varsayılan: False). |

**Kısıtlamalar:**

* Giriş `image` tam olarak bir görüntü olmalıdır.
* Giriş görüntüsünün minimum yüksekliği ve genişliği 160 piksel olmalıdır.
* Giriş görüntüsünün en-boy oranı 1:3 ile 3:1 arasında olmalıdır.
* Nihai çıktı boyutu (giriş boyutları `scale_factor` ile çarpıldığında) 25.300.000 pikseli aşamaz. Eğer `auto_downscale` devre dışı bırakılmışsa ve bu limit aşılacaksa, düğüm bir hata verecektir.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Yaratıcı bir şekilde geliştirilmiş ve büyütülmüş çıktı görüntüsü. |
