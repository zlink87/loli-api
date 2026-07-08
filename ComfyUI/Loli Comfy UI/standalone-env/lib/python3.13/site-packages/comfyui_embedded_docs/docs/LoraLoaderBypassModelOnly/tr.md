> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/LoraLoaderBypassModelOnly/tr.md)

Bu düğüm, bir modelin davranışını değiştirmek için LoRA (Düşük Dereceli Uyarlama) uygular, ancak yalnızca model bileşenini etkiler. Belirtilen bir LoRA dosyasını yükler ve modelin ağırlıklarını belirli bir güç değeriyle ayarlar; CLIP metin kodlayıcı gibi diğer bileşenleri değiştirmeden bırakır.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `model` | MODEL | Evet | - | LoRA ayarlamalarının uygulanacağı temel model. |
| `lora_name` | STRING | Evet | (Kullanılabilir LoRA dosyalarının listesi) | Yüklenecek ve uygulanacak LoRA dosyasının adı. Seçenekler `loras` dizinindeki dosyalardan doldurulur. |
| `strength_model` | FLOAT | Evet | -100.0 ile 100.0 | LoRA'nın model ağırlıkları üzerindeki etki gücü. Pozitif bir değer LoRA'yı uygular, negatif bir değer tersini uygular ve 0 değeri hiçbir etki yaratmaz (varsayılan: 1.0). |

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model` | MODEL | Ağırlıklarına LoRA ayarlamaları uygulanmış, değiştirilmiş model. |
