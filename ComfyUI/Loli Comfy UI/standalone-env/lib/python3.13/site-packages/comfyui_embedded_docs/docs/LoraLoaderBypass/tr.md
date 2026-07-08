> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypass/tr.md)

LoraLoaderBypass düğümü, bir difüzyon modeline ve bir CLIP modeline özel bir "bypass" (atlatma) modunda bir LoRA (Düşük Dereceli Uyarlama) uygular. Standart bir LoRA yükleyicisinden farklı olarak, bu yöntem temel modelin ağırlıklarını kalıcı olarak değiştirmez. Bunun yerine, çıktıyı LoRA'nın etkisini modelin normal ileri geçişine ekleyerek hesaplar. Bu, eğitim sırasında veya ağırlıkları dışarıya aktarılmış modellerle çalışırken kullanışlıdır.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Evet | - | LoRA'nın uygulanacağı difüzyon modeli. |
| `clip` | CLIP | Evet | - | LoRA'nın uygulanacağı CLIP modeli. |
| `lora_name` | COMBO | Evet | *Kullanılabilir LoRA dosyalarının listesi* | Uygulanacak LoRA dosyasının adı. Seçenekler `loras` klasöründen yüklenir. |
| `strength_model` | FLOAT | Evet | -100.0 ile 100.0 | Difüzyon modelini ne kadar güçlü değiştireceği. Bu değer negatif olabilir (varsayılan: 1.0). |
| `strength_clip` | FLOAT | Evet | -100.0 ile 100.0 | CLIP modelini ne kadar güçlü değiştireceği. Bu değer negatif olabilir (varsayılan: 1.0). |

**Not:** Hem `strength_model` hem de `strength_clip` 0 olarak ayarlanırsa, düğüm işleme tabi tutmadan orijinal, değiştirilmemiş `model` ve `clip` girişlerini döndürür.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `MODEL` | MODEL | LoRA'nın bypass modunda uygulandığı difüzyon modeli. |
| `CLIP` | CLIP | LoRA'nın bypass modunda uygulandığı CLIP modeli. |
