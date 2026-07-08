> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/EmptyAceStep1.5LatentAudio/tr.md)

Empty Ace Step 1.5 Latent Audio düğümü, ses işleme için tasarlanmış boş bir latent tensör oluşturur. Belirtilen süre ve batch boyutunda sessiz bir ses latent'i üretir; bu, ComfyUI'deki ses üretimi iş akışları için bir başlangıç noktası olarak kullanılabilir. Düğüm, latent uzunluğunu girilen saniye değerine ve sabit bir örnekleme hızına göre hesaplar.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `seconds` | FLOAT | Hayır | 1.0 - 1000.0 | Üretilecek sesin saniye cinsinden süresi (varsayılan: 120.0). |
| `batch_size` | INT | Hayır | 1 - 4096 | Batch içindeki latent görüntülerin sayısı (varsayılan: 1). |

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `LATENT` | LATENT | "audio" tür tanımlayıcısına sahip, sessiz sesi temsil eden boş bir latent tensör. |
