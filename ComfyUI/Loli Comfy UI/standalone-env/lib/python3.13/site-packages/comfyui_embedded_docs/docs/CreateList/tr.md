> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/CreateList/tr.md)

Create List düğümü, birden fazla girdiyi tek bir sıralı liste halinde birleştirir. Aynı veri türünden herhangi bir sayıda girdi alır ve bunları bağlandıkları sırayla birleştirir. Bu düğüm, bir iş akışındaki diğer düğümler tarafından işlenecek olan görüntü veya metin gibi veri gruplarını hazırlamak için kullanışlıdır.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `input_*` | Değişken | Evet | Herhangi | Değişken sayıda girdi yuvası. Artı (+) simgesine tıklayarak daha fazla girdi ekleyebilirsiniz. Tüm girdiler aynı veri türünde olmalıdır (örneğin, hepsi IMAGE veya hepsi STRING). |

**Not:** Düğüm, öğeleri bağladıkça otomatik olarak yeni girdi yuvaları oluşturacaktır. Düğümün doğru çalışması için bağlanan tüm girdiler aynı veri türünü paylaşmalıdır.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `list` | Değişken | Bağlanan girdilerdeki tüm öğeleri, sağlandıkları sırayla birleştirilmiş halde içeren tek bir liste. Çıktı veri türü, girdi veri türüyle eşleşir. |
