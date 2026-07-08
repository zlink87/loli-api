> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ImageToVideoNode/tr.md)

Vidu2 Görüntüden-Videoya Üretim düğümü, tek bir giriş görüntüsünden başlayarak bir video dizisi oluşturur. İsteğe bağlı bir metin istemi temelinde sahneyi canlandırmak için belirtilen bir Vidu2 modelini kullanır ve videonun uzunluğunu, çözünürlüğünü ve hareket yoğunluğunu kontrol eder.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq2-pro-fast"`<br>`"viduq2-pro"`<br>`"viduq2-turbo"` | Video üretimi için kullanılacak Vidu2 modeli. Farklı modeller, değişen hız ve kalite ödünleşimleri sunar. |
| `image` | IMAGE | Evet | - | Oluşturulacak videonun başlangıç karesi olarak kullanılacak bir görüntü. Yalnızca bir görüntüye izin verilir. |
| `prompt` | STRING | Hayır | - | Video üretimi için isteğe bağlı bir metin istemi (maksimum 2000 karakter). Varsayılan değer boş bir dizgidir. |
| `duration` | INT | Evet | 1 - 10 | Oluşturulan videonun saniye cinsinden uzunluğu. Varsayılan değer 5'tir. |
| `seed` | INT | Hayır | 0 - 2147483647 | Tekrarlanabilir sonuçlar sağlamak için rastgele sayı üretiminde kullanılan bir tohum değeri. Varsayılan değer 1'dir. |
| `resolution` | COMBO | Evet | `"720p"`<br>`"1080p"` | Oluşturulan videonun çıkış çözünürlüğü. |
| `movement_amplitude` | COMBO | Evet | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | Kare içindeki nesnelerin hareket genliği. |

**Kısıtlamalar:**

* `image` girişi tam olarak bir görüntü içermelidir.
* Giriş görüntüsünün en-boy oranı 1:4 ile 4:1 arasında olmalıdır.
* `prompt` metni maksimum 2000 karakter ile sınırlıdır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Oluşturulan video dosyası. |
