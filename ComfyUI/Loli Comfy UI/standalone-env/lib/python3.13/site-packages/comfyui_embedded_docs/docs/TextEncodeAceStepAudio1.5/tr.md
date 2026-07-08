> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/TextEncodeAceStepAudio1.5/tr.md)

TextEncodeAceStepAudio1.5 düğümü, AceStepAudio 1.5 modeliyle kullanılmak üzere metin ve sesle ilgili meta verileri hazırlar. Betimleyici etiketleri, şarkı sözlerini ve müzikal parametreleri alır, ardından bunları ses üretimi için uygun bir koşullandırma formatına dönüştürmek için bir CLIP modeli kullanır.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `clip` | CLIP | Evet | Yok | Giriş metnini tokenize etmek ve kodlamak için kullanılan CLIP modeli. |
| `tags` | STRING | Evet | Yok | Ses için tür, ruh hali veya enstrümanlar gibi betimleyici etiketler. Çok satırlı giriş ve dinamik prompt'ları destekler. |
| `lyrics` | STRING | Evet | Yok | Ses parçası için şarkı sözleri. Çok satırlı giriş ve dinamik prompt'ları destekler. |
| `seed` | INT | Hayır | 0 - 18446744073709551615 | Tekrarlanabilir üretim için bir rastgele seed değeri. `control_after_generate` widget'ına sahiptir. Varsayılan: 0. |
| `bpm` | INT | Hayır | 10 - 300 | Üretilen ses için dakika başına vuruş (BPM). Varsayılan: 120. |
| `duration` | FLOAT | Hayır | 0.0 - 2000.0 | Sesin saniye cinsinden istenen süresi. Varsayılan: 120.0. |
| `timesignature` | COMBO | Hayır | `"2"`<br>`"3"`<br>`"4"`<br>`"6"` | Müzikal zaman imzası. |
| `language` | COMBO | Hayır | `"en"`<br>`"ja"`<br>`"zh"`<br>`"es"`<br>`"de"`<br>`"fr"`<br>`"pt"`<br>`"ru"`<br>`"it"`<br>`"nl"`<br>`"pl"`<br>`"tr"`<br>`"vi"`<br>`"cs"`<br>`"fa"`<br>`"id"`<br>`"ko"`<br>`"uk"`<br>`"hu"`<br>`"ar"`<br>`"sv"`<br>`"ro"`<br>`"el"` | Giriş metninin dili. |
| `keyscale` | COMBO | Hayır | `"C major"`<br>`"C minor"`<br>`"C# major"`<br>`"C# minor"`<br>`"Db major"`<br>`"Db minor"`<br>`"D major"`<br>`"D minor"`<br>`"D# major"`<br>`"D# minor"`<br>`"Eb major"`<br>`"Eb minor"`<br>`"E major"`<br>`"E minor"`<br>`"F major"`<br>`"F minor"`<br>`"F# major"`<br>`"F# minor"`<br>`"Gb major"`<br>`"Gb minor"`<br>`"G major"`<br>`"G minor"`<br>`"G# major"`<br>`"G# minor"`<br>`"Ab major"`<br>`"Ab minor"`<br>`"A major"`<br>`"A minor"`<br>`"A# major"`<br>`"A# minor"`<br>`"Bb major"`<br>`"Bb minor"`<br>`"B major"`<br>`"B minor"` | Müzikal anahtar ve dizi (majör veya minör). |
| `generate_audio_codes` | BOOLEAN | Hayır | Yok | Ses kodları üreten LLM'yi etkinleştirir. Bu yavaş olabilir ancak üretilen sesin kalitesini artıracaktır. Modele bir ses referansı veriyorsanız bunu kapatın. Varsayılan: True. |
| `cfg_scale` | FLOAT | Hayır | 0.0 - 100.0 | Sınıflandırıcısız kılavuz ölçeği. Daha yüksek değerler, çıktının prompt'u daha yakından takip etmesini sağlar. Varsayılan: 2.0. |
| `temperature` | FLOAT | Hayır | 0.0 - 2.0 | Bir örnekleme sıcaklığı. Daha düşük değerler çıktıyı daha deterministik yapar. Varsayılan: 0.85. |
| `top_p` | FLOAT | Hayır | 0.0 - 2000.0 | Çekirdek örnekleme olasılığı (top-p). Varsayılan: 0.9. |
| `top_k` | INT | Hayır | 0 - 100 | Dikkate alınacak en yüksek olasılıklı token sayısı (top-k). Varsayılan: 0. |

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `CONDITIONING` | CONDITIONING | AceStepAudio 1.5 modeli için kodlanmış metin ve ses parametrelerini içeren koşullandırma verisi. |
