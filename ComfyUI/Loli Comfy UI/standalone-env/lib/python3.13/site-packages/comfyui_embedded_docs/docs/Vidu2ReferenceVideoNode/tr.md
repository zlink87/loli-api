> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/Vidu2ReferenceVideoNode/tr.md)

Vidu2 Referans-Görüntüden Video Üretme düğümü, bir metin istemi ve birden fazla referans görselinden bir video oluşturur. Her biri kendi referans görselleri setine sahip olmak üzere en fazla yedi özne tanımlayabilir ve bunlara `@subject{subject_id}` kullanarak istemde referans verebilirsiniz. Düğüm, yapılandırılabilir süre, en-boy oranı ve hareket ile bir video üretir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"viduq2"` | Video üretimi için kullanılacak yapay zeka modeli. |
| `subjects` | AUTOGROW | Evet | N/A | Her bir özne için en fazla 3 referans görseli sağlayın (tüm özneler arasında toplam 7 görsel). İstemlerde `@subject{subject_id}` aracılığıyla bunlara referans verin. |
| `prompt` | STRING | Evet | N/A | Video üretimini yönlendirmek için kullanılan metin açıklaması. `audio` parametresi etkinleştirildiğinde, video bu isteme dayalı olarak üretilen konuşma ve arka plan müziği içerecektir. |
| `audio` | BOOLEAN | Hayır | N/A | Etkinleştirildiğinde, video isteme dayalı olarak üretilen konuşma ve arka plan müziği içerecektir (varsayılan: `False`). |
| `duration` | INT | Hayır | 1 - 10 | Üretilen videonun saniye cinsinden uzunluğu (varsayılan: `5`). |
| `seed` | INT | Hayır | 0 - 2147483647 | Tekrarlanabilir sonuçlar için üretimin rastgeleliğini kontrol etmekte kullanılan bir sayı (varsayılan: `1`). |
| `aspect_ratio` | COMBO | Hayır | `"16:9"`<br>`"9:16"`<br>`"4:3"`<br>`"3:4"`<br>`"1:1"` | Video karesinin şekli (en-boy oranı). |
| `resolution` | COMBO | Hayır | `"720p"`<br>`"1080p"` | Çıktı videosunun piksel çözünürlüğü. |
| `movement_amplitude` | COMBO | Hayır | `"auto"`<br>`"small"`<br>`"medium"`<br>`"large"` | Kare içindeki nesnelerin hareket genliğini kontrol eder. |

**Kısıtlamalar:**

* `prompt` 1 ile 2000 karakter arasında uzunlukta olmalıdır.
* Birden fazla özne tanımlayabilirsiniz, ancak tüm özneler arasındaki toplam referans görseli sayısı 7'yi geçmemelidir.
* Her bir öznenin en fazla 3 referans görseli olabilir.
* Her bir referans görselinin genişlik-yükseklik oranı 1:4 ile 4:1 arasında olmalıdır.
* Her bir referans görselinin hem genişliği hem de yüksekliği en az 128 piksel olmalıdır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | VIDEO | Üretilen video dosyası. |
