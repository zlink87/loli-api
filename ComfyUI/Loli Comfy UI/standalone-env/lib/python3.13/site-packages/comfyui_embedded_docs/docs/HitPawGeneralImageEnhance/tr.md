> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/HitPawGeneralImageEnhance/tr.md)

Bu düğüm, düşük çözünürlüklü görüntüleri yükselterek süper çözünürlüğe getirir, artefaktları ve gürültüyü giderir. Görüntüyü işlemek için harici bir API kullanır ve işleme limitleri dahilinde kalmak için giriş boyutunu otomatik olarak ayarlayabilir. İzin verilen maksimum çıktı boyutu 4 megapikseldir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Evet | `"generative_portrait"`<br>`"generative"` | Kullanılacak iyileştirme modeli. |
| `image` | IMAGE | Evet | - | İyileştirilecek giriş görüntüsü. |
| `upscale_factor` | INT | Evet | `1`<br>`2`<br>`4` | Görüntü boyutlarının kaç kat büyütüleceği faktörü. |
| `auto_downscale` | BOOLEAN | Hayır | - | Çıktı limiti aşacaksa giriş görüntüsünü otomatik olarak küçült. (varsayılan: `False`) |

**Not:** Hesaplanan çıktı boyutu (giriş yüksekliği × upscale_factor × giriş genişliği × upscale_factor) 4.000.000 pikseli (4MP) aşarsa ve `auto_downscale` devre dışıysa, düğüm bir hata verecektir. `auto_downscale` etkinleştirildiğinde, düğüm istenen büyütme faktörünü uygulamadan önce giriş görüntüsünü limit dahiline sığacak şekilde küçültmeye çalışacaktır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | İyileştirilmiş ve büyütülmüş çıktı görüntüsü. |
