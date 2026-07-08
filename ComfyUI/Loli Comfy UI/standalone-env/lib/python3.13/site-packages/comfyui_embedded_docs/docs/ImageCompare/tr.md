> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ImageCompare/tr.md)

Image Compare düğümü, sürüklenebilir bir kaydırıcı kullanarak iki görüntüyü yan yana karşılaştırmak için görsel bir arayüz sağlar. Bu düğüm bir çıktı düğümü olarak tasarlanmıştır, yani verileri diğer düğümlere aktarmaz, bunun yerine görüntüleri doğrudan kullanıcı arayüzünde inceleme amacıyla görüntüler.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `image_a` | IMAGE | Hayır | - | Karşılaştırılacak ilk görüntü. |
| `image_b` | IMAGE | Hayır | - | Karşılaştırılacak ikinci görüntü. |
| `compare_view` | IMAGECOMPARE | Evet | - | Kullanıcı arayüzünde kaydırıcılı karşılaştırma görünümünü etkinleştiren kontrol. |

**Not:** Bu düğüm bir çıktı düğümüdür. `image_a` ve `image_b` isteğe bağlı olsa da, düğümün görünür bir etkiye sahip olması için en az bir görüntü sağlanmalıdır. Düğüm, bağlı olmayan herhangi bir görüntü girişi için boş bir alan görüntüler.

## Çıktılar

Bu düğüm bir çıktı düğümüdür ve diğer düğümlerde kullanılmak üzere herhangi bir veri çıktısı üretmez. İşlevi, sağlanan görüntüleri ComfyUI arayüzünde görüntülemektir.
