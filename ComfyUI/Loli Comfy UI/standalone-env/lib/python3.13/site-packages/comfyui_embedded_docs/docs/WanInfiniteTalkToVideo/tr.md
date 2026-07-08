> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/WanInfiniteTalkToVideo/tr.md)

WanInfiniteTalkToVideo düğümü, ses girişinden video dizileri oluşturur. Bir veya iki konuşmacıdan çıkarılan ses özellikleriyle koşullandırılmış bir video difüzyon modeli kullanarak, konuşan kafa videosunun gizli (latent) temsilini üretir. Düğüm, yeni bir dizi oluşturabilir veya hareket bağlamı için önceki kareleri kullanarak mevcut bir diziyi genişletebilir.

## Girişler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `mode` | COMBO | Evet | `"single_speaker"`<br>`"two_speakers"` | Ses giriş modu. `"single_speaker"` tek bir ses girişi kullanır. `"two_speakers"`, ikinci bir konuşmacı ve karşılık gelen maskeler için girişleri etkinleştirir. |
| `model` | MODEL | Evet | - | Temel video difüzyon modeli. |
| `model_patch` | MODELPATCH | Evet | - | Ses projeksiyon katmanlarını içeren model yaması. |
| `positive` | CONDITIONING | Evet | - | Üretimi yönlendirmek için kullanılan pozitif koşullandırma. |
| `negative` | CONDITIONING | Evet | - | Üretimi yönlendirmek için kullanılan negatif koşullandırma. |
| `vae` | VAE | Evet | - | Görüntüleri gizli uzaya kodlamak ve gizli uzaydan çözmek için kullanılan VAE. |
| `width` | INT | Hayır | 16 - MAX_RESOLUTION | Çıktı videosunun piksel cinsinden genişliği. 16'ya bölünebilir olmalıdır. (varsayılan: 832) |
| `height` | INT | Hayır | 16 - MAX_RESOLUTION | Çıktı videosunun piksel cinsinden yüksekliği. 16'ya bölünebilir olmalıdır. (varsayılan: 480) |
| `length` | INT | Hayır | 1 - MAX_RESOLUTION | Oluşturulacak kare sayısı. (varsayılan: 81) |
| `clip_vision_output` | CLIPVISIONOUTPUT | Hayır | - | Ek koşullandırma için isteğe bağlı CLIP görüntü çıktısı. |
| `start_image` | IMAGE | Hayır | - | Video dizisini başlatmak için isteğe bağlı bir başlangıç görüntüsü. |
| `audio_encoder_output_1` | AUDIOENCODEROUTPUT | Evet | - | İlk konuşmacı için özellikleri içeren birincil ses kodlayıcı çıktısı. |
| `motion_frame_count` | INT | Hayır | 1 - 33 | Bir diziyi genişletirken hareket bağlamı olarak kullanılacak önceki kare sayısı. (varsayılan: 9) |
| `audio_scale` | FLOAT | Hayır | -10.0 - 10.0 | Ses koşullandırmasına uygulanan bir ölçeklendirme faktörü. (varsayılan: 1.0) |
| `previous_frames` | IMAGE | Hayır | - | Genişletmek için isteğe bağlı önceki video kareleri. |
| `audio_encoder_output_2` | AUDIOENCODEROUTPUT | Hayır | - | İkinci ses kodlayıcı çıktısı. `mode` `"two_speakers"` olarak ayarlandığında gereklidir. |
| `mask_1` | MASK | Hayır | - | İlk konuşmacı için maske, iki ses girişi kullanılıyorsa gereklidir. |
| `mask_2` | MASK | Hayır | - | İkinci konuşmacı için maske, iki ses girişi kullanılıyorsa gereklidir. |

**Parametre Kısıtlamaları:**

* `mode` `"two_speakers"` olarak ayarlandığında, `audio_encoder_output_2`, `mask_1` ve `mask_2` parametreleri zorunlu hale gelir.
* `audio_encoder_output_2` sağlanırsa, `mask_1` ve `mask_2` de sağlanmalıdır.
* `mask_1` ve `mask_2` sağlanırsa, `audio_encoder_output_2` de sağlanmalıdır.
* `previous_frames` sağlanırsa, `motion_frame_count` ile belirtilen sayıda en az kare içermelidir.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `model` | MODEL | Ses koşullandırması uygulanmış yamalı model. |
| `positive` | CONDITIONING | Ek bağlamla (örn. başlangıç görüntüsü, CLIP görüntüsü) potansiyel olarak değiştirilmiş pozitif koşullandırma. |
| `negative` | CONDITIONING | Ek bağlamla potansiyel olarak değiştirilmiş negatif koşullandırma. |
| `latent` | LATENT | Gizli uzayda oluşturulan video dizisi. |
| `trim_image` | INT | Bir diziyi genişletirken, hareket bağlamının başından itibaren kırpılması gereken kare sayısı. |
