> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WavespeedImageUpscaleNode/tr.md)

WaveSpeed Görüntü Ölçekleme düğümü, bir görüntünün çözünürlüğünü ve kalitesini artırmak için harici bir AI servisi kullanır. Tek bir girdi fotoğrafı alır ve onu 2K, 4K veya 8K gibi daha yüksek bir hedef çözünürlüğe ölçekleyerek, daha keskin ve detaylı bir sonuç üretir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | STRING | Evet | `"SeedVR2"`<br>`"Ultimate"` | Ölçekleme için kullanılacak AI modeli. "SeedVR2" ve "Ultimate", farklı kalite ve fiyatlandırma seviyeleri sunar. |
| `image` | IMAGE | Evet | | Ölçeklenecek girdi görüntüsü. |
| `target_resolution` | STRING | Evet | `"2K"`<br>`"4K"`<br>`"8K"` | Ölçeklenmiş görüntü için istenen çıktı çözünürlüğü. |

**Not:** Bu düğüm tam olarak bir girdi görüntüsü gerektirir. Bir grup görüntü sağlamak hata ile sonuçlanacaktır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `image` | IMAGE | Ölçeklenmiş, yüksek çözünürlüklü çıktı görüntüsü. |
