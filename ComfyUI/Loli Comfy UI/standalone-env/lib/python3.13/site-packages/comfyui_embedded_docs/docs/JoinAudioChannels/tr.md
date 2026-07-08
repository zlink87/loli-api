> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/JoinAudioChannels/tr.md)

Join Audio Channels düğümü, iki ayrı mono ses girişini tek bir stereo ses çıkışında birleştirir. Bir sol kanal ve bir sağ kanal alır, uyumlu örnekleme hızlarına ve uzunluklara sahip olmalarını sağlar ve bunları iki kanallı bir ses dalga formunda birleştirir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `audio_left` | AUDIO | Evet | | Ortaya çıkan stereo seste sol kanal olarak kullanılacak mono ses verisi. |
| `audio_right` | AUDIO | Evet | | Ortaya çıkan stereo seste sağ kanal olarak kullanılacak mono ses verisi. |

**Not:** Her iki giriş ses akışı da mono (tek kanallı) olmalıdır. Farklı örnekleme hızlarına sahiplerse, daha düşük hıza sahip kanal otomatik olarak daha yüksek hızla eşleşecek şekilde yeniden örneklenir. Ses akışları farklı uzunluklara sahipse, daha kısa olanın uzunluğuna göre kırpılırlar.

## Çıkışlar

| Çıkış Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `audio` | AUDIO | Birleştirilmiş sol ve sağ kanalları içeren ortaya çıkan stereo ses. |
