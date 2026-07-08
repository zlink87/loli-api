> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ColorToRGBInt/tr.md)

ColorToRGBInt düğümü, onaltılık formatta belirtilen bir rengi tek bir tamsayı değerine dönüştürür. `#FF5733` gibi bir renk dizesini alır ve kırmızı, yeşil ve mavi bileşenlerini birleştirerek karşılık gelen RGB tamsayısını hesaplar.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `color` | STRING | Evet | N/A | Onaltılık format `#RRGGBB` şeklinde bir renk değeri. |

**Not:** Giriş `color` dizesi tam olarak 7 karakter uzunluğunda olmalı ve `#` sembolü ile başlamalı, ardından altı onaltılık basamak gelmelidir (örneğin, kırmızı için `#FF0000`). Format hatalıysa düğüm bir hata verecektir.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `rgb_int` | INT | Hesaplanan RGB tamsayı değeri. Bu değer şu formülden türetilir: `(Kırmızı * 65536) + (Yeşil * 256) + Mavi`. |
