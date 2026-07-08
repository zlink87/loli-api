> تم إنشاء هذه الوثيقة بواسطة الذكاء الاصطناعي. إذا وجدت أي أخطاء أو لديك اقتراحات للتحسين، فلا تتردد في المساهمة! [تحرير على GitHub](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MagnificImageStyleTransferNode/ar.md)

يُطبِّق هذا العقدة النمط البصري من صورة مرجعية على صورتك المدخلة. يستخدم خدمة ذكاء اصطناعي خارجية لمعالجة الصور، مما يتيح لك التحكم في قوة نقل النمط والحفاظ على هيكل الصورة الأصلية.

## المدخلات

| المعامل | نوع البيانات | مطلوب | النطاق | الوصف |
|-----------|-----------|----------|-------|-------------|
| `image` | IMAGE | نعم | - | الصورة المراد تطبيق نقل النمط عليها. |
| `reference_image` | IMAGE | نعم | - | الصورة المرجعية لاستخراج النمط منها. |
| `prompt` | STRING | لا | - | نص توجيهي اختياري لتوجيه عملية نقل النمط. |
| `style_strength` | INT | لا | 0 إلى 100 | نسبة قوة النمط (القيمة الافتراضية: 100). |
| `structure_strength` | INT | لا | 0 إلى 100 | يحافظ على هيكل الصورة الأصلية (القيمة الافتراضية: 50). |
| `flavor` | COMBO | لا | "faithful"<br>"gen_z"<br>"psychedelia"<br>"detaily"<br>"clear"<br>"donotstyle"<br>"donotstyle_sharp" | نكهة نقل النمط. |
| `engine` | COMBO | لا | "balanced"<br>"definio"<br>"illusio"<br>"3d_cartoon"<br>"colorful_anime"<br>"caricature"<br>"real"<br>"super_real"<br>"softy" | اختيار محرك المعالجة. |
| `portrait_mode` | COMBO | لا | "disabled"<br>"enabled" | تمكين وضع الصور الشخصية لتحسينات الوجه. |
| `portrait_style` | COMBO | لا | "standard"<br>"pop"<br>"super_pop" | النمط البصري المطبق على الصور الشخصية. هذا المدخل متاح فقط عندما يتم تعيين `portrait_mode` على "enabled". |
| `portrait_beautifier` | COMBO | لا | "none"<br>"beautify_face"<br>"beautify_face_max" | شدة تجميل الوجه على الصور الشخصية. هذا المدخل متاح فقط عندما يتم تعيين `portrait_mode` على "enabled". |
| `fixed_generation` | BOOLEAN | لا | - | عند تعطيله، توقع أن تُدخل كل عملية توليد درجة من العشوائية، مما يؤدي إلى نتائج أكثر تنوعًا (القيمة الافتراضية: True). |

**القيود:**

* مطلوب بالضبط صورة واحدة `image` وصورة مرجعية واحدة `reference_image`.
* يجب أن يكون لكلا الصورتين نسبة أبعاد بين 1:3 و 3:1.
* يجب أن يكون لكلا الصورتين ارتفاع وعرض لا يقل عن 160 بكسل.
* معاملات `portrait_style` و `portrait_beautifier` تكون نشطة ومطلوبة فقط عندما يتم تعيين `portrait_mode` على "enabled".

## المخرجات

| اسم المخرج | نوع البيانات | الوصف |
|-------------|-----------|-------------|
| `image` | IMAGE | الصورة الناتجة بعد تطبيق نقل النمط. |
