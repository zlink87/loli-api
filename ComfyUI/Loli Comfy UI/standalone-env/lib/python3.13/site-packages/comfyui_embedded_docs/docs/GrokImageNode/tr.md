> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/GrokImageNode/tr.md)

Grok Image düğümü, Grok AI modelini kullanarak bir metin açıklamasına dayalı bir veya daha fazla görüntü oluşturur. İsteğinizi harici bir servise gönderir ve iş akışınızda kullanılabilecek tensörler olarak oluşturulan görüntüleri döndürür.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | COMBO | Evet | `"grok-imagine-image-beta"` | Görüntü oluşturma için kullanılacak belirli Grok modeli. |
| `prompt` | STRING | Evet | Yok | Görüntüyü oluşturmak için kullanılan metin isteği. Bu açıklama, yapay zekanın ne oluşturacağına rehberlik eder. |
| `aspect_ratio` | COMBO | Evet | `"1:1"`<br>`"2:3"`<br>`"3:2"`<br>`"3:4"`<br>`"4:3"`<br>`"9:16"`<br>`"16:9"`<br>`"9:19.5"`<br>`"19.5:9"`<br>`"9:20"`<br>`"20:9"`<br>`"1:2"`<br>`"2:1"` | Oluşturulan görüntü için istenen genişlik-yükseklik oranı. |
| `number_of_images` | INT | Hayır | 1'den 10'a | Oluşturulacak görüntü sayısı (varsayılan: 1). |
| `seed` | INT | Hayır | 0'dan 2147483647'ye | Düğümün yeniden çalıştırılıp çalıştırılmayacağını belirleyen bir başlangıç değeri. Gerçek görüntü sonuçları belirleyici değildir ve aynı başlangıç değeriyle bile değişiklik gösterecektir (varsayılan: 0). |

**Not:** `seed` parametresi öncelikle, bir iş akışı içinde düğümün ne zaman yeniden yürütüleceğini kontrol etmek için kullanılır. Harici yapay zeka servisinin doğası gereği, oluşturulan görüntüler aynı başlangıç değeri kullanılsa bile çalıştırmalar arasında tekrarlanabilir veya aynı olmayacaktır.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `output` | IMAGE | Oluşturulan görüntü veya bir grup görüntü. Eğer `number_of_images` 1 ise, tek bir görüntü tensörü döndürülür. 1'den büyükse, bir grup görüntü tensörü döndürülür. |
