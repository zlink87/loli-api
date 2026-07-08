> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/ReferenceTimbreAudio/tr.md)

Bu düğüm, "ace step 1.5" işlemi için kullanılacak bir referans ses tınısı belirler. Bir koşullandırma girdisi ve isteğe bağlı olarak bir sesin gizli temsilini alarak çalışır, ardından bu gizli veriyi koşullandırmaya ekleyerek iş akışındaki sonraki düğümler tarafından kullanılmasını sağlar.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `conditioning` | CONDITIONING | Evet | | Referans ses bilgisinin ekleneceği koşullandırma verisi. |
| `latent` | LATENT | Hayır | | İsteğe bağlı referans ses gizli temsili. Sağlandığında, örnekleri koşullandırmaya eklenir. |

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `conditioning` | CONDITIONING | Değiştirilmiş koşullandırma verisi. İsteğe bağlı `latent` girdisi sağlandıysa, artık referans ses tınısı gizli verilerini içerir. |
