> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageRelightNode/tr.md)

Magnific Image Relight düğümü, bir girdi görüntüsünün aydınlatmasını ayarlar. Metin istemine dayalı stilistik aydınlatma uygulayabilir veya isteğe bağlı bir referans görüntüsünden aydınlatma özelliklerini aktarabilir. Düğüm, nihai çıktının parlaklığı, kontrastı ve genel havasını hassas bir şekilde ayarlamak için çeşitli kontroller sunar.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | Evet | Yok | Aydınlatması değiştirilecek görüntü. Tam olarak bir görüntü gereklidir. Minimum boyutlar 160x160 pikseldir. En-boy oranı 1:3 ile 3:1 arasında olmalıdır. |
| `prompt` | STRING | Hayır | Yok | Aydınlatma için açıklayıcı yönlendirme. Vurgu notasyonunu destekler (1-1.4). Varsayılan değer boş bir dizgidir. |
| `light_transfer_strength` | INT | Evet | 0 - 100 | Işık aktarım uygulamasının yoğunluğu. Varsayılan: 100. |
| `style` | COMBO | Evet | `"standard"`<br>`"darker_but_realistic"`<br>`"clean"`<br>`"smooth"`<br>`"brighter"`<br>`"contrasted_n_hdr"`<br>`"just_composition"` | Stilistik çıktı tercihi. |
| `interpolate_from_original` | BOOLEAN | Evet | Yok | Üretim özgürlüğünü orijinale daha yakın eşleşecek şekilde kısıtlar. Varsayılan: False. |
| `change_background` | BOOLEAN | Evet | Yok | Arka planı istem/referansa göre değiştirir. Varsayılan: True. |
| `preserve_details` | BOOLEAN | Evet | Yok | Orijinalden doku ve ince detayları korur. Varsayılan: True. |
| `advanced_settings` | DYNAMICCOMBO | Evet | `"disabled"`<br>`"enabled"` | Gelişmiş aydınlatma kontrolü için hassas ayar seçenekleri. `"enabled"` olarak ayarlandığında, ek parametreler kullanılabilir hale gelir. |
| `reference_image` | IMAGE | Hayır | Yok | Aydınlatma aktarımı için isteğe bağlı referans görüntüsü. Sağlanırsa, tam olarak bir görüntü gereklidir. Minimum boyutlar 160x160 pikseldir. En-boy oranı 1:3 ile 3:1 arasında olmalıdır. |

**Gelişmiş Ayarlar Notu:** `advanced_settings` `"enabled"` olarak ayarlandığında, aşağıdaki iç içe parametreler etkinleşir:

* `whites`: Görüntüdeki en parlak tonları ayarlar. Aralık: 0 - 100. Varsayılan: 50.
* `blacks`: Görüntüdeki en koyu tonları ayarlar. Aralık: 0 - 100. Varsayılan: 50.
* `brightness`: Genel parlaklık ayarı. Aralık: 0 - 100. Varsayılan: 50.
* `contrast`: Kontrast ayarı. Aralık: 0 - 100. Varsayılan: 50.
* `saturation`: Renk doygunluğu ayarı. Aralık: 0 - 100. Varsayılan: 50.
* `engine`: İşleme motoru seçimi. Seçenekler: `"automatic"`, `"balanced"`, `"cool"`, `"real"`, `"illusio"`, `"fairy"`, `"colorful_anime"`, `"hard_transform"`, `"softy"`.
* `transfer_light_a`: Işık aktarımının yoğunluğu. Seçenekler: `"automatic"`, `"low"`, `"medium"`, `"normal"`, `"high"`, `"high_on_faces"`.
* `transfer_light_b`: Ayrıca ışık aktarım yoğunluğunu değiştirir. Önceki kontrolle birleştirilerek çeşitli efektler elde edilebilir. Seçenekler: `"automatic"`, `"composition"`, `"straight"`, `"smooth_in"`, `"smooth_out"`, `"smooth_both"`, `"reverse_both"`, `"soft_in"`, `"soft_out"`, `"soft_mid"`, `"style_shift"`, `"strong_shift"`.
* `fixed_generation`: Aynı ayarlarla tutarlı çıktı sağlar. Varsayılan: True.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Aydınlatması değiştirilmiş görüntü. |
