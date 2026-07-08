> Bu belge yapay zeka tarafından oluşturulmuştur. Herhangi bir hata bulursanız veya iyileştirme önerileriniz varsa, katkıda bulunmaktan çekinmeyin! [GitHub'da Düzenle](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/RecraftCreateStyleNode/tr.md)

Bu düğüm, referans görseller yükleyerek görsel oluşturma için özel bir stil yaratır. Yeni stili tanımlamak için 1 ile 5 arasında görsel yükleyebilirsiniz ve düğüm, diğer Recraft düğümleriyle kullanılabilecek benzersiz bir stil kimliği döndürür. Yüklenen tüm görsellerin toplam dosya boyutu 5 MB'ı geçmemelidir.

## Girdiler

| Parametre | Veri Türü | Zorunlu | Aralık | Açıklama |
|-----------|-----------|----------|-------|-------------|
| `style` | STRING | Evet | `"realistic_image"`<br>`"digital_illustration"` | Oluşturulan görsellerin temel stili. |
| `images` | IMAGE | Evet | 1 ile 5 görsel | Özel stili oluşturmak için kullanılan 1 ile 5 arasında referans görsel seti. |

**Not:** `images` girdisindeki tüm görsellerin toplam dosya boyutu 5 MB'tan az olmalıdır. Bu sınır aşılırsa düğüm başarısız olur.

## Çıktılar

| Çıktı Adı | Veri Türü | Açıklama |
|-------------|-----------|-------------|
| `style_id` | STRING | Yeni oluşturulan özel stil için benzersiz tanımlayıcı. |
