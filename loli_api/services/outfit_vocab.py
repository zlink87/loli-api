"""
Outfit & clothing vocabulary — single source of truth.

Maps every OutfitType to a nudity-graded description, and every AccessoryType
to a phrase. Shared by:
  * the outfit-EDIT path (api/v1/endpoints/outfit.py) — imperative "change the
    outfit to ..." instructions, and
  * the character-GENERATION path (services/prompt_generator.py) — declarative
    "wearing ..." clauses so a new character is dressed at the requested nudity
    level instead of defaulting nude on the NSFW-tuned base model.

Tier semantics (dressed-by-default), a 5-level ladder ordered least to most
explicit — LOW < SUGGESTIVE < MEDIUM < REVEALING < HIGH:
  * LOW        the garment actually worn as designed — real clothing,
               flattering fit, zero exposure/sheer/cutout language.
  * SUGGESTIVE still fully clothed but with a teasing edge: tighter fit,
               shorter hem, deeper neckline, one strap down, a hint of skin —
               no exposed nipples/genitals, nothing explicit.
  * MEDIUM     partial nudity: unbuttoned/undone, lingerie peeking through,
               real exposure (cleavage, sideboob, underboob) — but the bust stays
               COVERED or LINED: naming nipples, or sheer-over-a-bare-bust wording
               that renders them, is REVEALING+ vocabulary, never MEDIUM (product
               decision 2026-07-14, guard-tested in test_outfit_vocab_tiers). NAKED
               is the one exemption — it is nudity itself, not a garment, so its
               "partial nudity" IS topless.
  * REVEALING  mostly undone or displaced: garment barely covering, one or
               both breasts exposed or fully sheer, bottoms pushed aside or
               pulled down but not removed — more exposed than MEDIUM, short
               of HIGH's full explicitness.
  * HIGH       explicit.
Exposure is strictly opt-in past LOW; a LOW-nudity request must never render
a costume that is secretly half-undressed.
"""
import random
from typing import Dict, List, Optional, Set

from models.enums import OutfitType, AccessoryType, NudityLevel, WardrobeStyleType


OUTFIT_DESCRIPTIONS: Dict[OutfitType, Dict[NudityLevel, str]] = {
    OutfitType.RED_EVENING_GOWN: {
        NudityLevel.LOW: "an elegant red evening gown with a flattering V-neckline, fabric skimming her curves gracefully, a thigh-high slit that moves with her stride",
        NudityLevel.SUGGESTIVE: "a striking red evening gown with a deep V-neckline teasing a hint of cleavage, fabric skimming her curves more closely, thigh-high slit riding higher with every step",
        NudityLevel.MEDIUM: "a stunning red evening gown with a plunging neckline showing deep cleavage, fabric hugging every curve tightly, thigh-high slit revealing toned leg",
        NudityLevel.REVEALING: "a daring red evening gown with a plunging neckline barely containing one breast, fabric clinging to every curve like a second skin, thigh-high slit parting all the way up to bare hip with each stride",
        NudityLevel.HIGH: "a scandalously plunging red evening gown with fabric so thin it clings to every curve, deep neckline dropping below the navel to bare the inner swell of both breasts, thigh-high slit parting to reveal bare hip and the shadow of bare sex with each slow step",
    },
    OutfitType.LITTLE_BLACK_DRESS: {
        NudityLevel.LOW: "a classic fitted little black dress with a flattering scoop neckline, hem falling just above the knee, sleek and elegant silhouette",
        NudityLevel.SUGGESTIVE: "a snug little black dress with a deeper scoop neckline showing a hint of cleavage, hem shortened to mid-thigh, sleek silhouette with a teasing edge",
        NudityLevel.MEDIUM: "a tight little black dress with a low-cut front showing cleavage, hem riding high on the thighs, side cut-outs hinting at sideboob",
        NudityLevel.REVEALING: "a scandalously tight little black dress with a low-cut front spilling cleavage, hem riding up to the hips, side cut-outs baring full sideboob",
        NudityLevel.HIGH: "a wickedly short little black dress that rides high enough to flash bare ass cheeks, plunging front barely containing spilling breasts, side cut-outs exposing sideboob and the curve under each nipple",
    },
    OutfitType.WHITE_SUMMER_DRESS: {
        NudityLevel.LOW: "a light white summer dress with a flowing A-line skirt, thin adjustable straps, hem fluttering just above the knees",
        NudityLevel.SUGGESTIVE: "a light white summer dress in thinner fabric, one strap slipping off the shoulder, hem fluttering higher above the knees, no bra hinted beneath the fabric",
        NudityLevel.MEDIUM: "a thin white summer dress that hints at the silhouette underneath in bright light, a low scooped neckline baring deep cleavage, hem fluttering at mid-thigh",
        NudityLevel.REVEALING: "a sheer white summer dress that turns see-through in direct light, no bra so the outline of her nipples shows plainly through the fabric, hem riding up to the tops of the thighs",
        NudityLevel.HIGH: "a whisper-thin, almost transparent white summer dress that turns completely see-through in light, no bra or panties so hard nipples and the dark triangle of pubic hair are clearly visible, hem fluttering just below the curve of the ass",
    },
    OutfitType.FLORAL_MAXI_DRESS: {
        NudityLevel.LOW: "a flowing one-piece floral maxi dress that falls in a single continuous sweep from a fitted bodice to the ankle, soft fabric moving gracefully with each step",
        NudityLevel.SUGGESTIVE: "a flowing one-piece floral maxi dress with a deep V-neckline that dips to show a hint of cleavage, soft fabric skimming the body and moving gracefully with each step",
        NudityLevel.MEDIUM: "a deep-wrap floral maxi dress with a loose tie showing generous cleavage and the curve of breasts, fabric flowing and hinting at the body underneath",
        NudityLevel.REVEALING: "a deep-wrap floral maxi dress with the tie barely holding, wrap falling open to bare one breast and a long stretch of thigh with every step",
        NudityLevel.HIGH: "a deep-wrap floral maxi dress tied so loosely it constantly slips open, fully exposing heavy breasts and the smooth mound between parted thighs whenever she moves",
    },
    OutfitType.COCKTAIL_DRESS: {
        NudityLevel.LOW: "a glittering sequined silver cocktail dress with a halter neckline, knee-length hem, fabric shimmering elegantly under the light",
        NudityLevel.SUGGESTIVE: "a glittering sequined silver cocktail dress with a halter neckline dipping lower, hem shortened above the knee, fabric shimmering tightly over her curves",
        NudityLevel.MEDIUM: "a glittering sequined silver cocktail dress with halter neck, deep front showing cleavage, fabric shimmering against curves",
        NudityLevel.REVEALING: "a glittering sequined silver cocktail dress with the halter front gaping open to the sternum, one sequined strap slipped off the shoulder baring the side of a breast, fabric shimmering against bare skin",
        NudityLevel.HIGH: "a glittering sequined silver cocktail dress with halter straps that beg to be untied, front open from collarbone to crotch, sequins sparkling against bare skin and erect nipples",
    },
    OutfitType.BODYCON_DRESS: {
        NudityLevel.LOW: "a fitted navy bodycon dress that skims her silhouette, knee-length hem, sleek and confident",
        NudityLevel.SUGGESTIVE: "a fitted navy bodycon dress in a slightly clingier stretch, neckline scooped lower, hem shortened to just above the knee, sleek silhouette with a teasing pull",
        NudityLevel.MEDIUM: "a skin-tight navy bodycon dress hugging every curve, fabric stretched over breasts and hips, hem riding up to mid-thigh",
        NudityLevel.REVEALING: "a skin-tight navy bodycon dress molded to every curve, hem rucked up to the hips baring the lower curve of her ass, fabric straining thin enough to outline her nipples",
        NudityLevel.HIGH: "an obscenely tight navy bodycon dress molded like liquid latex to every inch, riding up to expose lower ass cheeks and the clear outline of swollen labia",
    },
    OutfitType.BUSINESS_SUIT: {
        NudityLevel.LOW: "a tailored black business suit with a crisp buttoned blouse underneath, blazer sharply cut, trousers fitted and professional",
        NudityLevel.SUGGESTIVE: "a tailored black business suit with the blouse's top buttons undone, blazer fitted close, trousers riding low enough to show a strip of bare waist",
        NudityLevel.MEDIUM: "a tailored black business suit with blazer unbuttoned over a sheer blouse, a black lace bra beneath it, deep cleavage visible, trousers fitted tightly around hips",
        NudityLevel.REVEALING: "a tailored black business suit with the blazer worn open over an unbuttoned, sheer blouse baring one breast, trousers unfastened and riding low on the hips",
        NudityLevel.HIGH: "a severely tailored black business suit worn completely unbuttoned, no blouse or bra underneath so full breasts hang free, trousers slung dangerously low to show the top of the pubic cleft",
    },
    OutfitType.BLAZER_TROUSERS: {
        NudityLevel.LOW: "a sharp grey blazer worn over a fitted top, matching tailored trousers, a clean and confident office look",
        NudityLevel.SUGGESTIVE: "a sharp grey blazer left mostly unbuttoned over a fitted top, cleavage peeking at the neckline, matching trousers riding low on the hips",
        NudityLevel.MEDIUM: "a sharp grey blazer worn open over a lace bralette showing cleavage, matching trousers fitted low on the hips",
        NudityLevel.REVEALING: "a sharp grey blazer worn open over a sheer lace bralette baring one breast, matching trousers unfastened and gaping at the waist",
        NudityLevel.HIGH: "a sharp grey blazer worn open over nothing but skin, breasts fully exposed, matching trousers unfastened and pulled down just enough to reveal the bare lower belly and hint of slit",
    },
    OutfitType.PENCIL_SKIRT_SET: {
        NudityLevel.LOW: "a fitted pencil skirt with a tucked-in blouse, tailored and professional, skirt hugging her hips to the knee",
        NudityLevel.SUGGESTIVE: "a fitted pencil skirt with the blouse knotted at the waist baring a strip of midriff, skirt hugging her hips a little higher above the knee",
        NudityLevel.MEDIUM: "a skin-tight pencil skirt with a sheer blouse knotted high, showing midriff and the outline of a lace bra, skirt hugging hips tightly",
        NudityLevel.REVEALING: "a skin-tight pencil skirt with the back zipper pulled halfway down baring skin to the small of her back, sheer blouse knotted high enough to show underboob",
        NudityLevel.HIGH: "a skin-tight pencil skirt with the zipper fully down the back exposing round bare ass, sheer blouse knotted high to permanently display underboob and stiff nipples",
    },
    OutfitType.TUXEDO: {
        NudityLevel.LOW: "a feminine black satin-lapel tuxedo over a fitted white shirt, sharply tailored trousers, sleek and confident",
        NudityLevel.SUGGESTIVE: "a feminine black satin-lapel tuxedo with the white shirt unbuttoned low, a hint of cleavage at the collar, trousers fitted low and sleek on the hips",
        NudityLevel.MEDIUM: "a feminine black satin-lapel tuxedo with no shirt underneath, waistcoat showing deep cleavage, trousers fitted low on hips",
        NudityLevel.REVEALING: "a feminine black satin-lapel tuxedo worn with the waistcoat open over bare skin baring the underside of both breasts, trousers riding low enough to show hip bones",
        NudityLevel.HIGH: "a feminine black satin-lapel tuxedo reimagined slutty: no shirt, waistcoat open to bare cleavage to navel, trousers cut so low the cleft of the buttocks and hip bones are on full display",
    },
    OutfitType.DENIM_JACKET_JEANS: {
        NudityLevel.LOW: "a cropped denim jacket over a fitted tank top, high-rise jeans, casual and effortless",
        NudityLevel.SUGGESTIVE: "a cropped denim jacket left unbuttoned over a fitted tank top, a hint of midriff showing, jeans riding lower on the hips",
        NudityLevel.MEDIUM: "a cropped denim jacket over a tiny bralette showing cleavage and midriff, low-rise jeans hugging hips tightly",
        NudityLevel.REVEALING: "a cropped denim jacket hanging open over a tiny bralette that barely covers, one breast slipping free at the edge, low-rise jeans unbuttoned and gaping at the waist",
        NudityLevel.HIGH: "a cropped denim jacket flung open over bare breasts, nipples peeking out, low-rise jeans unbuttoned and tugged down past the pubic bone to show smooth shaved mound",
    },
    OutfitType.GRAPHIC_TEE_SHORTS: {
        NudityLevel.LOW: "a relaxed cropped graphic tee showing a hint of midriff, denim shorts, casual and playful",
        NudityLevel.SUGGESTIVE: "a snug cropped graphic tee riding higher to bare more midriff, denim shorts cut shorter and riding up on the thighs, casual and flirtatious",
        NudityLevel.MEDIUM: "a tiny cropped graphic tee showing underboob and midriff, micro denim shorts hugging tightly and riding up on the thighs",
        NudityLevel.REVEALING: "a tiny cropped graphic tee stretched thin and riding up to flash the underside of her breasts, micro denim shorts hugging so tight they dig deep into every curve",
        NudityLevel.HIGH: "a tiny cropped graphic tee ending right under the nipples, breasts almost fully out, micro denim shorts so tight they dig into the ass crack and camel-toe prominently",
    },
    OutfitType.HOODIE_JOGGERS: {
        NudityLevel.LOW: "an oversized zip-up hoodie over a fitted tank top, matching joggers, cozy and relaxed",
        NudityLevel.SUGGESTIVE: "an oversized zip-up hoodie unzipped partway to hint at cleavage, matching joggers slung a little lower on the hips, cozy but teasing",
        NudityLevel.MEDIUM: "an oversized hoodie worn unzipped showing cleavage and bare skin underneath, joggers slung low on the hips",
        NudityLevel.REVEALING: "an oversized hoodie unzipped low with nothing but a thin cami underneath, one breast slipping into view at the edge, joggers tugged down to show hip bones",
        NudityLevel.HIGH: "an oversized hoodie worn unzipped to the navel with nothing underneath, heavy breasts spilling free, joggers pulled down to mid-thigh exposing bare pussy",
    },
    OutfitType.FLANNEL_SHIRT: {
        NudityLevel.LOW: "a large flannel shirt tied at the waist over a fitted tank top, casual and cozy",
        NudityLevel.SUGGESTIVE: "a large flannel shirt left mostly unbuttoned over a fitted tank top, tied loosely at the waist, a hint of cleavage showing at the collar",
        NudityLevel.MEDIUM: "a large flannel shirt worn open and tied under the bust, showing cleavage and toned midriff, lace underwear peeking out",
        NudityLevel.REVEALING: "a large flannel shirt worn open and tied just under the bust with nothing but lace underneath, one breast slipping free of the fabric, lace underwear on full display",
        NudityLevel.HIGH: "a huge flannel shirt worn open and tied high under bare breasts, black lace thong pulled aside to reveal her bare pussy",
    },
    OutfitType.CROP_TOP_CARGO: {
        NudityLevel.LOW: "a fitted white crop top showing a hint of midriff, low-slung cargo pants, sporty and casual",
        NudityLevel.SUGGESTIVE: "a fitted white crop top cut shorter to bare more midriff, low-slung cargo pants sitting just below the hip bones, sporty and teasing",
        NudityLevel.MEDIUM: "a tiny white crop top showing underboob and toned midriff, low-slung cargo pants unbuttoned at the waist",
        NudityLevel.REVEALING: "a tiny white crop top riding up to flash the full underboob, low-slung cargo pants unbuttoned and hanging open at the waist",
        NudityLevel.HIGH: "a minuscule white crop top sliced so high the entire underboob and lower curve of breasts are exposed, cargo pants unbuttoned and gaping open at the front",
    },
    OutfitType.YOGA_OUTFIT: {
        NudityLevel.LOW: "a fitted black sports bra, high-waisted leggings clinging to her curves, sporty and athletic",
        NudityLevel.SUGGESTIVE: "a fitted black sports bra with a lower scoop showing a hint of cleavage, high-waisted leggings clinging tighter to her curves, sporty and toned",
        NudityLevel.MEDIUM: "a tight black sports bra with deep cut-outs showing sideboob, high-waisted leggings clinging to every curve",
        NudityLevel.REVEALING: "a tight black sports bra with wide cut-outs baring the outer curve of each breast, high-waisted leggings so sheer and thin they cling into every crease",
        NudityLevel.HIGH: "a barely-there black sports bra with massive cut-outs leaving nipples and most of each breast bare, high-cut leggings split at the crotch for easy access",
    },
    OutfitType.TENNIS_OUTFIT: {
        NudityLevel.LOW: "a short white tennis skirt, fitted white polo shirt, sporty and energetic",
        NudityLevel.SUGGESTIVE: "a short white tennis skirt hemmed a little higher, fitted polo shirt with the top button undone, sporty and playful",
        NudityLevel.MEDIUM: "a short white tennis skirt flashing toned thighs with each move, fitted polo cropped to show midriff, sporty and flirtatious",
        NudityLevel.REVEALING: "a short white tennis skirt that flashes the curve of bare ass with every bounce, polo cropped and unbuttoned low enough to show the underside of her breasts",
        NudityLevel.HIGH: "a scandalously short white tennis skirt that flashes bare ass and pussy with every bounce, polo cropped and unbuttoned to navel with breasts jiggling free",
    },
    OutfitType.RUNNING_GEAR: {
        NudityLevel.LOW: "a neon athletic tank top, fitted compression shorts, sporty and ready to move",
        NudityLevel.SUGGESTIVE: "a neon athletic tank top with a lower scoop neckline hinting at cleavage, fitted compression shorts cut shorter on the thigh, sporty and energetic",
        NudityLevel.MEDIUM: "a neon tank top with deep side slits showing sideboob, tiny compression shorts hugging curves tightly",
        NudityLevel.REVEALING: "a neon tank top with side slits torn wide enough to bare full sideboob, tiny compression shorts riding up into a thong that exposes most of her ass",
        NudityLevel.HIGH: "a neon tank sliced open at sides and front so breasts bounce completely exposed, tiny compression shorts cut into a thong exposing ass cheeks and labia",
    },
    OutfitType.GYM_SET: {
        NudityLevel.LOW: "a glossy purple sports bra and matching bike shorts, fabric fitted over her curves, sporty and confident",
        NudityLevel.SUGGESTIVE: "a glossy purple sports bra cut a little lower and matching bike shorts riding higher on the hips, fabric fitted tightly, sporty and confident",
        NudityLevel.MEDIUM: "a glossy purple micro sports bra and matching bike shorts, fabric stretched tight over curves, showing deep cleavage and toned midriff",
        NudityLevel.REVEALING: "a glossy purple micro sports bra stretched thin enough to outline her nipples, matching bike shorts pulled into a high-cut thong baring most of her ass",
        NudityLevel.HIGH: "a glossy purple micro sports bra that only covers nipples and matching bike shorts with wide crotchless opening, pussy and ass fully on display",
    },
    OutfitType.ONE_PIECE_SWIMSUIT: {
        NudityLevel.LOW: "a high-leg black one-piece swimsuit with a flattering neckline, fabric hugging her curves, classic and elegant",
        NudityLevel.SUGGESTIVE: "a high-leg black one-piece swimsuit with a deeper neckline hinting at cleavage, fabric cut higher on the hips, classic silhouette with a teasing edge",
        NudityLevel.MEDIUM: "a high-leg black one-piece swimsuit with plunging neckline and side cut-outs, showing cleavage and sideboob, fabric hugging every curve",
        NudityLevel.REVEALING: "a high-leg black one-piece swimsuit with a plunging neckline barely containing her breasts, side cut-outs baring full sideboob down to the hip",
        NudityLevel.HIGH: "a high-leg black one-piece with extreme plunges and side cut-outs that remove all coverage of side-boob, nipples, and most of the pubic mound",
    },
    OutfitType.BIKINI: {
        NudityLevel.LOW: "a scarlet string bikini, triangle top and tied-hip bottoms, flirtatious and beach-ready",
        NudityLevel.SUGGESTIVE: "a scarlet string bikini with slightly smaller triangles riding higher on the hips, strings tied loosely, flirtatious and beach-ready",
        NudityLevel.MEDIUM: "a scarlet string bikini with small triangles showing generous cleavage, strings tied at the hips, flirtatious and revealing",
        NudityLevel.REVEALING: "a scarlet string bikini with one triangle pushed aside to bare a nipple, hip strings loosened and riding low on her hips, barely holding on",
        NudityLevel.HIGH: "a scarlet micro-string bikini — tiniest triangles imaginable barely covering nipples, strings pulled aside to leave labia and clit piercing exposed",
    },
    OutfitType.LEATHER_JACKET: {
        NudityLevel.LOW: "a black leather biker jacket over a fitted top, tight leather pants, edgy and confident",
        NudityLevel.SUGGESTIVE: "a black leather biker jacket left unzipped over a fitted top, a hint of cleavage at the neckline, tight leather pants riding low on the hips",
        NudityLevel.MEDIUM: "a black leather biker jacket worn open over a lace bralette, showing cleavage and toned midriff, tight leather pants",
        NudityLevel.REVEALING: "a black leather biker jacket hanging open over a sheer lace bralette that barely covers, one breast slipping free at the edge, tight leather pants unzipped at the waist",
        NudityLevel.HIGH: "a black leather biker jacket worn wide open over bare skin, full breast and nipple exposure, paired with only a visible clit ring and nothing else",
    },
    OutfitType.TRENCH_COAT: {
        NudityLevel.LOW: "a belted beige trench coat, classic and tailored, cinched at the waist",
        NudityLevel.SUGGESTIVE: "a belted beige trench coat worn loosely cinched, top button undone to show collarbone and a hint of cleavage, classic and tailored",
        NudityLevel.MEDIUM: "a belted beige trench coat slightly open showing bare collarbone, hint of cleavage, and bare legs underneath suggesting nudity beneath",
        NudityLevel.REVEALING: "a belted beige trench coat hanging open at the front, baring one breast and a long stretch of bare leg, belt barely holding it closed",
        NudityLevel.HIGH: "a belted beige trench coat worn completely open and nude underneath — full-frontal nudity, breasts swaying, bare pussy on display as she walks",
    },
    OutfitType.PUFFER_JACKET: {
        NudityLevel.LOW: "an oversized pastel puffer jacket zipped over a fitted top, cozy and casual",
        NudityLevel.SUGGESTIVE: "an oversized pastel puffer jacket unzipped partway over a fitted top, a hint of cleavage at the collar, cozy but teasing",
        NudityLevel.MEDIUM: "an oversized pastel puffer jacket partially unzipped showing bare skin and cleavage underneath, hinting at nudity beneath",
        NudityLevel.REVEALING: "an oversized pastel puffer jacket unzipped to the sternum with nothing underneath, baring the curve of one breast whenever it shifts open",
        NudityLevel.HIGH: "an oversized pastel puffer jacket unzipped to the crotch with nothing underneath, breasts and bare sex revealed every time it parts",
    },
    OutfitType.FUR_COAT: {
        NudityLevel.LOW: "a plush faux fur coat draped elegantly over her shoulders, glamorous and luxurious",
        NudityLevel.SUGGESTIVE: "a plush faux fur coat draped loosely over her shoulders, one lapel slipping to hint at bare collarbone, glamorous and teasing",
        NudityLevel.MEDIUM: "a plush faux fur coat draped off one shoulder, revealing bare skin and the curve of one breast, wearing a tiny thong underneath",
        NudityLevel.REVEALING: "a plush faux fur coat slipping further off both shoulders, baring one breast fully and most of the other, a tiny thong the only thing underneath",
        NudityLevel.HIGH: "a plush faux fur coat left hanging open off the shoulders, revealing only bare skin, erect nipples, and a tiny thong pulled to the side",
    },
    OutfitType.KIMONO: {
        NudityLevel.LOW: "a silk kimono tied neatly with an obi sash, flowing sleeves, elegant and traditional",
        NudityLevel.SUGGESTIVE: "a silk kimono tied looser at the obi, the collar gaping to hint at cleavage, flowing sleeves, elegant with a teasing edge",
        NudityLevel.MEDIUM: "a silk kimono loosely tied, falling open at the chest to reveal deep cleavage and smooth skin, obi barely holding it together",
        NudityLevel.REVEALING: "a silk kimono barely held by a loosely knotted obi, falling open to bare one full breast and a long stretch of thigh with each step",
        NudityLevel.HIGH: "a silk kimono worn completely untied and fallen open down the front, heavy breasts and bare pussy on full display, obi loose around the waist",
    },
    OutfitType.SARI: {
        NudityLevel.LOW: "an orange-gold sari draped elegantly, fitted blouse, fabric flowing gracefully",
        NudityLevel.SUGGESTIVE: "an orange-gold sari draped a little lower on the hips, fitted blouse cut to show a hint of midriff, fabric flowing gracefully",
        NudityLevel.MEDIUM: "a sheer orange-gold sari draped low on the hips, tiny blouse showing deep cleavage and midriff, fabric hinting at the body beneath",
        NudityLevel.REVEALING: "a sheer orange-gold sari draped low enough to bare the navel and hip, tiny blouse riding up to flash underboob beneath the sheer fabric",
        NudityLevel.HIGH: "a sheer orange-gold sari draped obscenely low below the pubic bone, tiny blouse cropped to bare underboob and hard nipples",
    },
    OutfitType.CHEONGSAM: {
        NudityLevel.LOW: "a fitted red silk cheongsam with a mandarin collar and side slit, elegant and traditional",
        NudityLevel.SUGGESTIVE: "a fitted red silk cheongsam with the side slit cut higher on the thigh, top button of the mandarin collar left undone, elegant with a teasing edge",
        NudityLevel.MEDIUM: "a skin-tight red silk cheongsam with high slits showing toned thighs, front buttons partially undone revealing cleavage",
        NudityLevel.REVEALING: "a skin-tight red silk cheongsam with slits rising past the hip, front buttons undone to the sternum baring the curve of one breast",
        NudityLevel.HIGH: "a skin-tight red silk cheongsam with slits rising to the waist, front buttons undone to below the navel exposing deep cleavage and bare mound",
    },
    OutfitType.HANBOK: {
        NudityLevel.LOW: "a pastel hanbok with a fitted jeogori top and a flowing chima skirt, graceful and traditional",
        NudityLevel.SUGGESTIVE: "a pastel hanbok with the jeogori tie loosened to show collarbone, chima skirt slit a little higher to reveal toned thigh, graceful with a teasing edge",
        NudityLevel.MEDIUM: "a pastel hanbok with jeogori slightly open showing collarbone and hint of cleavage, chima flowing with a slit revealing toned thigh",
        NudityLevel.REVEALING: "a pastel hanbok with jeogori untied and gaping to bare the curve of one breast, chima slit rising to the hip to reveal bare thigh and the side of her ass",
        NudityLevel.HIGH: "a pastel hanbok with jeogori cropped and pushed below the breasts, chima slit to hip revealing bare thigh, ass, and side of pussy",
    },
    OutfitType.DIRNDL: {
        NudityLevel.LOW: "a laced dirndl bodice over a white blouse, full skirt falling to the knee, traditional and flattering",
        NudityLevel.SUGGESTIVE: "a laced dirndl bodice cinched tighter over the white blouse, neckline scooped lower to hint at cleavage, skirt shortened above the knee",
        NudityLevel.MEDIUM: "a tight-laced dirndl bodice pushing up generous cleavage, skirt short enough to show thighs, flirtatious and traditional",
        NudityLevel.REVEALING: "a tight-laced dirndl bodice loosened enough to spill cleavage over the top, blouse pushed off one shoulder baring skin, skirt hiked short enough to flash bare thigh",
        NudityLevel.HIGH: "a tight-laced dirndl bodice shoved down below both breasts, skirt flipped up or scandalously short to expose bare sex and round ass",
    },
    OutfitType.SEQUIN_TOP_SKIRT: {
        NudityLevel.LOW: "a sparkling sequin top, fitted black skirt to the knee, glamorous and ready for a night out",
        NudityLevel.SUGGESTIVE: "a sparkling sequin top cropped to show a hint of midriff, fitted black skirt shortened above the knee, glamorous and flirtatious",
        NudityLevel.MEDIUM: "a sparkling sequin crop top showing cleavage and midriff, micro black skirt hugging hips tightly and riding high on the thighs",
        NudityLevel.REVEALING: "a sparkling sequin crop top riding up to bare the underside of her breasts, micro black skirt hiked high enough to flash the curve of bare ass",
        NudityLevel.HIGH: "a sparkling sequin crop top ending below the nipples with no bra, micro black skirt constantly riding up to flash bare pussy and ass",
    },
    OutfitType.VELVET_DRESS: {
        NudityLevel.LOW: "a deep burgundy velvet dress with a flattering neckline, fabric hugging her curves elegantly",
        NudityLevel.SUGGESTIVE: "a deep burgundy velvet dress with a lower neckline hinting at cleavage, back dipping open to the shoulder blades, fabric hugging her curves",
        NudityLevel.MEDIUM: "a deep burgundy velvet dress with plunging neckline showing cleavage, back open to mid-back, fabric hugging curves",
        NudityLevel.REVEALING: "a deep burgundy velvet dress with the neckline plunging to bare the outer curve of both breasts, back open nearly to the small of her back",
        NudityLevel.HIGH: "a deep burgundy velvet dress with neckline plunging past both breasts to the waist, back completely bare to the tailbone",
    },
    OutfitType.SATIN_SLIP_DRESS: {
        NudityLevel.LOW: "a champagne satin slip dress with thin straps, fabric skimming her curves, knee-length and elegant",
        NudityLevel.SUGGESTIVE: "a champagne satin slip dress with one thin strap slipping off the shoulder, fabric skimming closer to her curves, hem shortened above the knee",
        NudityLevel.MEDIUM: "a champagne satin slip dress with thin straps, a low cowl neckline baring deep cleavage, fabric clinging to curves, short hem showing thighs",
        NudityLevel.REVEALING: "a champagne satin slip dress with both straps loosened and slipping, fabric clinging to reveal the shape of her nipples through the satin, hem riding up to the thighs",
        NudityLevel.HIGH: "a champagne satin slip so short it rides above the ass cheeks, thin straps fallen off shoulders leaving breasts fully bare and nipples hard",
    },
    OutfitType.JUMPSUIT: {
        NudityLevel.LOW: "a sleek black jumpsuit with a flattering neckline, fitted waist, sleek and modern",
        NudityLevel.SUGGESTIVE: "a sleek black jumpsuit with a deeper neckline hinting at cleavage, fitted waist cinched tighter, sleek and modern with a teasing edge",
        NudityLevel.MEDIUM: "a sleek black jumpsuit with plunging front showing cleavage to the navel, side cut-outs at the waist exposing bare skin",
        NudityLevel.REVEALING: "a sleek black jumpsuit with the plunging front open past the sternum baring the inner curve of her breasts, side cut-outs baring full sideboob",
        NudityLevel.HIGH: "a sleek black jumpsuit with plunging front diving to the pubic bone, sides completely cut out from armpit to hip exposing sideboob and hip bones",
    },
    OutfitType.POLKA_DOT_DRESS_50S: {
        NudityLevel.LOW: "a 1950s polka dot swing dress with a sweetheart neckline, full skirt falling below the knee, cheerful and retro",
        NudityLevel.SUGGESTIVE: "a 1950s polka dot swing dress with the sweetheart neckline dipping a little lower, full skirt hemmed above the knee, cheerful and flirtatious",
        NudityLevel.MEDIUM: "a 1950s polka dot swing dress with sweetheart neckline pushed low showing cleavage, skirt hemmed short to show thighs",
        NudityLevel.REVEALING: "a 1950s polka dot swing dress with the sweetheart neckline tugged down to bare the top of both breasts, skirt hemmed short enough to flash bare thigh",
        NudityLevel.HIGH: "a 1950s polka dot swing dress with sweetheart neckline yanked down below both breasts, skirt hemmed micro-short to flash everything",
    },
    OutfitType.BELL_BOTTOMS_70S: {
        NudityLevel.LOW: "flared 1970s bell bottoms, a flowing bohemian blouse tucked in, retro and free-spirited",
        NudityLevel.SUGGESTIVE: "flared 1970s bell bottoms riding low on the hips, bohemian blouse left untucked with a couple buttons undone, retro and free-spirited",
        NudityLevel.MEDIUM: "low-slung 1970s bell bottoms showing hip bones, sheer bohemian blouse unbuttoned to show cleavage and lace bra",
        NudityLevel.REVEALING: "low-slung 1970s bell bottoms unbuttoned at the waist, sheer bohemian blouse hanging open with the lace bra pushed aside to bare one breast",
        NudityLevel.HIGH: "low-slung 1970s bell bottoms worn open at front with no panties, sheer bohemian blouse completely unbuttoned to bare breasts",
    },
    OutfitType.POWER_SUIT_80S: {
        NudityLevel.LOW: "a bold 1980s power suit with strong shoulder pads, fitted blouse underneath, skirt to the knee, confident and sharp",
        NudityLevel.SUGGESTIVE: "a bold 1980s power suit with the blouse's top buttons undone, strong shoulder pads framing a hint of cleavage, skirt shortened above the knee",
        NudityLevel.MEDIUM: "a bold 1980s power suit worn open over a lace bralette, strong shoulders, skirt short showing toned thighs and garter straps",
        NudityLevel.REVEALING: "a bold 1980s power suit worn open over a sheer lace bralette baring one breast, strong shoulders sharp above it, skirt hiked to show garter straps",
        NudityLevel.HIGH: "a bold 1980s power suit worn open — breasts fully out, strong shoulders framing erect nipples, skirt hiked to show bare ass and garters",
    },
    OutfitType.SILK_PAJAMAS: {
        NudityLevel.LOW: "a pale blue silk pajama set, top buttoned over a soft camisole, relaxed bottoms, cozy and elegant",
        NudityLevel.SUGGESTIVE: "a pale blue silk pajama set, top left unbuttoned by one or two buttons over the camisole, bottoms slung a little lower on the hips, cozy and teasing",
        NudityLevel.MEDIUM: "a pale blue silk pajama set with top unbuttoned showing cleavage and bare skin, bottoms slung low on the hips",
        NudityLevel.REVEALING: "a pale blue silk pajama set worn open past the camisole baring one breast, bottoms slung low enough to show hip bones",
        NudityLevel.HIGH: "a pale blue silk pajama set worn wide open, bottoms tugged down to thighs exposing bare pussy and hard nipples",
    },
    OutfitType.LACE_BODYSUIT: {
        NudityLevel.LOW: "a black lace-trimmed bodysuit with a smooth opaque lining beneath the lace, hugging her curves modestly, elegant and confident",
        NudityLevel.SUGGESTIVE: "a black lace-trimmed bodysuit with a thinner lining that hints at the shape of her curves, hugging her body closely, elegant with a teasing edge",
        NudityLevel.MEDIUM: "a black lace bodysuit with sheer lace panels at the waist and hips, an opaque-lined bust with deep cleavage on show, hugging every curve",
        NudityLevel.REVEALING: "a sheer black lace bodysuit with the lace pattern doing little to hide her nipples, one strap slipped off the shoulder, hugging every curve",
        NudityLevel.HIGH: "a sheer black lace bodysuit with open cups and crotchless design, nipples and bare folds completely uncovered",
    },
    OutfitType.SATIN_ROBE: {
        NudityLevel.LOW: "a deep red satin robe tied neatly at the waist, falling to the knee, silky and elegant",
        NudityLevel.SUGGESTIVE: "a deep red satin robe tied loosely at the waist, collar gaping to hint at cleavage, silky fabric shifting with every movement",
        NudityLevel.MEDIUM: "a deep red satin robe loosely tied, slipping off one shoulder to reveal bare skin and the curve of one breast, belt barely holding it closed",
        NudityLevel.REVEALING: "a deep red satin robe slipping off one shoulder and hanging open at the front, baring one breast fully and a long stretch of bare stomach",
        NudityLevel.HIGH: "a deep red satin robe slipping off both shoulders and hanging open, revealing bare breasts, stomach, and bare sex",
    },
    OutfitType.OVERSIZED_STREETWEAR: {
        NudityLevel.LOW: "an oversized cropped hoodie over a fitted tank top, baggy cargo pants, relaxed streetwear style",
        NudityLevel.SUGGESTIVE: "an oversized cropped hoodie riding up to hint at midriff, fitted tank top underneath, baggy cargo pants slung a little lower on the hips",
        NudityLevel.MEDIUM: "an oversized cropped hoodie showing underboob and midriff, baggy cargos slung low on the hips showing hip bones",
        NudityLevel.REVEALING: "an oversized cropped hoodie riding up to bare the underside of her breasts, baggy cargos unbuttoned and hanging open at the waist",
        NudityLevel.HIGH: "an oversized cropped hoodie barely covering underboob, baggy cargos unbuttoned and open at front showing bare mound",
    },
    OutfitType.BOMBER_JACKET_FIT: {
        NudityLevel.LOW: "a cropped bomber jacket over a fitted top, skinny jeans, casual and stylish",
        NudityLevel.SUGGESTIVE: "a cropped bomber jacket left unzipped over a fitted top, a hint of cleavage at the collar, skinny jeans riding low on the hips",
        NudityLevel.MEDIUM: "a cropped bomber jacket open over a tiny bralette showing cleavage, low-slung skinny jeans hugging hips tightly",
        NudityLevel.REVEALING: "a cropped bomber jacket hanging open over a tiny bralette that barely covers, one breast slipping free at the edge, low-slung skinny jeans unbuttoned at the waist",
        NudityLevel.HIGH: "a cropped bomber jacket flung open over bare bouncing breasts, low-slung skinny jeans revealing the top of the pubic slit",
    },
    OutfitType.NURSE_UNIFORM: {
        NudityLevel.LOW: "a fitted white nurse uniform dress, knee-length hem, crisp and professional",
        NudityLevel.SUGGESTIVE: "a fitted white nurse uniform dress with the top button undone, hem shortened above the knee, crisp but flirtatious",
        NudityLevel.MEDIUM: "a tight white nurse minidress with buttons straining over cleavage, skirt short showing thighs, suggestive and flirtatious",
        NudityLevel.REVEALING: "a tight white nurse minidress unbuttoned low enough to spill cleavage over the top, skirt hiked short enough to flash bare thigh and the curve of her ass",
        NudityLevel.HIGH: "a slutty white nurse minidress unbuttoned to the waist, breasts spilling out, skirt so short bare ass and pussy peek from behind",
    },
    OutfitType.SCHOOL_UNIFORM: {
        NudityLevel.LOW: "a classic school uniform: a buttoned blouse tucked into a pleated skirt at the knee, knee-high socks",
        NudityLevel.SUGGESTIVE: "a classic school uniform with the blouse's top buttons undone and left untucked, pleated skirt hemmed shorter above the knee, knee-high socks",
        NudityLevel.MEDIUM: "a naughty schoolgirl outfit: blouse tied high showing midriff and cleavage, micro-pleated skirt barely covering, thigh-high stockings",
        NudityLevel.REVEALING: "a naughty schoolgirl outfit: blouse tied high enough to bare the underside of her breasts, micro-pleated skirt riding up to flash bare ass, thigh-high stockings",
        NudityLevel.HIGH: "a naughty schoolgirl outfit: blouse tied under bare breasts, micro-pleated skirt flipped up exposing bare pussy and round ass",
    },
    OutfitType.MILITARY_UNIFORM: {
        NudityLevel.LOW: "a tailored military dress uniform jacket, matching skirt to the knee, sharp and disciplined",
        NudityLevel.SUGGESTIVE: "a tailored military dress uniform jacket with the top button undone to hint at cleavage, matching skirt hemmed shorter above the knee, sharp and disciplined",
        NudityLevel.MEDIUM: "a tight military dress uniform with jacket partially open showing cleavage, skirt short showing thighs and garter straps",
        NudityLevel.REVEALING: "a tight military dress uniform with the jacket open to the sternum baring the curve of one breast, skirt hiked high enough to show garter straps",
        NudityLevel.HIGH: "a tight military dress uniform with jacket open to navel, breasts fully out, skirt hiked high to bare ass and garter straps",
    },
    OutfitType.CHEF_UNIFORM: {
        NudityLevel.LOW: "a fitted white chef jacket, black slim-fit trousers, crisp and professional",
        NudityLevel.SUGGESTIVE: "a fitted white chef jacket with the top buttons undone to hint at cleavage, black slim-fit trousers riding lower on the hips, crisp but teasing",
        NudityLevel.MEDIUM: "a cropped white chef jacket showing cleavage and midriff, tiny black shorts hugging curves tightly",
        NudityLevel.REVEALING: "a cropped white chef jacket hanging open over bare skin baring one breast, tiny black shorts unbuttoned and riding low on the hips",
        NudityLevel.HIGH: "a cropped white chef jacket worn open with breasts hanging free, tiny black shorts pulled down or aside to reveal bare folds",
    },
    OutfitType.NAKED: {
        NudityLevel.LOW: "wearing only a sheer see-through covering draped loosely over the body, curves and silhouette fully visible, nipples and intimate areas hinted through the fabric",
        NudityLevel.SUGGESTIVE: "wearing only a sheer see-through covering that clings damply and gapes with every movement, fabric slipping lower with each step, nipples and intimate areas more clearly visible through the thin material",
        NudityLevel.MEDIUM: "topless with bare breasts and hard nipples exposed, wearing only a tiny thong, smooth bare skin",
        NudityLevel.REVEALING: "topless with bare breasts and nipples exposed, wearing only a thong pulled aside to bare her pussy lips, smooth bare skin",
        NudityLevel.HIGH: "completely naked, bare natural skin, hard nipples, swollen aroused pussy lips parted slightly, body on full explicit display",
    },
}


# ---------------------------------------------------------------------------
# Outfit exposure CAP — the most explicit nudity level a garment can HONESTLY show
# ---------------------------------------------------------------------------
# The reported bug: a batch item labeled "Mostly nude" (REVEALING) rendered a fully
# dressed graphic-tee + denim shorts. Mechanism: the edit model resolves the
# contradiction (a covering garment asked for near-nude exposure) toward the GARMENT
# noun, so the label lies. This map states, per outfit, the ceiling level the garment
# can actually render at — the planner then keeps each item's nudityLevel <= this cap
# (swapping/re-picking outfits, or, as a last resort, lowering the LABEL so it stays
# truthful). Exactly the same gap class the LOCATION_NUDITY_CEILING table closes for
# places; this one closes it for garments.
#
# Classification principle (conservative, render-empirical — cap = what the garment
# NOUN will reliably show, because the model renders the noun, not the aspirational
# tier prose):
#   * MEDIUM     — garment stays fundamentally DRESSED at its high tier: the model
#                  renders it as itself and it bares at most cleavage / leg / midriff /
#                  sideboob. Every structured dress & gown, tee/jeans/street outfit,
#                  suit, jumpsuit, activewear (sports bra + leggings/shorts read as
#                  activewear), covering one-piece swimsuit, traditional drape
#                  (sari/cheongsam/hanbok/dirndl — yards of fabric read clothed),
#                  loungewear pajamas, and the four uniforms.
#   * REVEALING  — minimal / sheer / slip / micro / open-drape pieces the model renders
#                  as barely-there: string bikini, sheer summer dress, satin slip,
#                  sequin micro club set, lace bodysuit, and the STRUCTURED open coats
#                  (leather / fur / puffer) which frame a mostly-bare body but read as a
#                  coat, not full frontal. "Mostly nude, covering little."
#   * HIGH       — literally naked, OR the thin open-front-over-nothing pieces whose
#                  whole design is to hang open and bare breasts AND sex: NAKED, the
#                  satin robe and silk kimono (thin boudoir robes that fall fully open),
#                  and the trench coat (the flasher trope — worn open over nothing,
#                  full-frontal). Bulky/structured coats stay REVEALING; thin robes that
#                  are MEANT to be worn open reach HIGH.
# Judgment calls (documented per the plan's "judge individually"):
#   - satin_robe / kimono -> HIGH not REVEALING: their own high tier is "hanging open,
#     bare breasts, stomach and bare sex" — an open-front robe is exactly the "arguably
#     HIGH" case the plan calls out.
#   - trench_coat -> HIGH (nude-underneath flasher) but fur/puffer/leather -> REVEALING:
#     the trench is a thin drape that renders as a clean full-frontal reveal; the others
#     are bulky/structured and render as a coat over a mostly-bare body.
#   - white_summer_dress -> REVEALING (its high tier is explicitly see-through/transparent),
#     unlike the opaque dresses which stay MEDIUM.
#   - activewear + one_piece_swimsuit -> MEDIUM: a sports bra / swimsuit renders with the
#     core covered no matter how the tier prose escalates (the exact lesson of the bug).
# Every OutfitType is mapped (a coverage test makes an unmapped value impossible);
# outfit_exposure_cap() still defaults MEDIUM defensively.
OUTFIT_EXPOSURE_CAP: Dict[OutfitType, NudityLevel] = {
    # --- dresses & gowns: render as a dress -> MEDIUM (cleavage/leg, still dressed) ---
    OutfitType.RED_EVENING_GOWN: NudityLevel.MEDIUM,
    OutfitType.LITTLE_BLACK_DRESS: NudityLevel.MEDIUM,
    OutfitType.FLORAL_MAXI_DRESS: NudityLevel.MEDIUM,
    OutfitType.COCKTAIL_DRESS: NudityLevel.MEDIUM,
    OutfitType.BODYCON_DRESS: NudityLevel.MEDIUM,
    OutfitType.VELVET_DRESS: NudityLevel.MEDIUM,
    OutfitType.POLKA_DOT_DRESS_50S: NudityLevel.MEDIUM,
    OutfitType.JUMPSUIT: NudityLevel.MEDIUM,
    # sheer/slip dresses render see-through / barely-there -> REVEALING
    OutfitType.WHITE_SUMMER_DRESS: NudityLevel.REVEALING,   # high tier = transparent
    OutfitType.SATIN_SLIP_DRESS: NudityLevel.REVEALING,     # thin clingy slip, lingerie-class
    # --- tailored / formal: a suit reads as a suit -> MEDIUM ---
    OutfitType.BUSINESS_SUIT: NudityLevel.MEDIUM,
    OutfitType.BLAZER_TROUSERS: NudityLevel.MEDIUM,
    OutfitType.PENCIL_SKIRT_SET: NudityLevel.MEDIUM,
    OutfitType.TUXEDO: NudityLevel.MEDIUM,
    OutfitType.POWER_SUIT_80S: NudityLevel.MEDIUM,
    # --- casual / street: top + bottoms read dressed -> MEDIUM (the exact bug item) ---
    OutfitType.DENIM_JACKET_JEANS: NudityLevel.MEDIUM,
    OutfitType.GRAPHIC_TEE_SHORTS: NudityLevel.MEDIUM,      # the reported "Mostly nude" tee
    OutfitType.HOODIE_JOGGERS: NudityLevel.MEDIUM,
    OutfitType.FLANNEL_SHIRT: NudityLevel.MEDIUM,
    OutfitType.CROP_TOP_CARGO: NudityLevel.MEDIUM,
    OutfitType.OVERSIZED_STREETWEAR: NudityLevel.MEDIUM,
    OutfitType.BOMBER_JACKET_FIT: NudityLevel.MEDIUM,
    OutfitType.BELL_BOTTOMS_70S: NudityLevel.MEDIUM,
    # --- activewear: sports bra + leggings/shorts render as activewear -> MEDIUM ---
    OutfitType.YOGA_OUTFIT: NudityLevel.MEDIUM,
    OutfitType.TENNIS_OUTFIT: NudityLevel.MEDIUM,
    OutfitType.RUNNING_GEAR: NudityLevel.MEDIUM,
    OutfitType.GYM_SET: NudityLevel.MEDIUM,
    # --- swim: covering one-piece -> MEDIUM; string bikini -> REVEALING ---
    OutfitType.ONE_PIECE_SWIMSUIT: NudityLevel.MEDIUM,
    OutfitType.BIKINI: NudityLevel.REVEALING,
    # --- structured outerwear: renders as a coat over a mostly-bare body -> REVEALING ---
    OutfitType.LEATHER_JACKET: NudityLevel.REVEALING,
    OutfitType.PUFFER_JACKET: NudityLevel.REVEALING,
    OutfitType.FUR_COAT: NudityLevel.REVEALING,
    # --- traditional drapes: yards of fabric read heavily clothed -> MEDIUM ---
    OutfitType.SARI: NudityLevel.MEDIUM,
    OutfitType.CHEONGSAM: NudityLevel.MEDIUM,
    OutfitType.HANBOK: NudityLevel.MEDIUM,
    OutfitType.DIRNDL: NudityLevel.MEDIUM,
    # --- eveningwear / lingerie / loungewear ---
    OutfitType.SEQUIN_TOP_SKIRT: NudityLevel.REVEALING,     # micro sequin club set
    OutfitType.LACE_BODYSUIT: NudityLevel.REVEALING,        # sheer lace bodysuit
    OutfitType.SILK_PAJAMAS: NudityLevel.MEDIUM,            # loungewear, renders covered
    # --- thin open-front-over-nothing robes/coats + naked -> HIGH ---
    OutfitType.SATIN_ROBE: NudityLevel.HIGH,                # boudoir robe, falls fully open
    OutfitType.KIMONO: NudityLevel.HIGH,                    # silk robe, unties fully open
    OutfitType.TRENCH_COAT: NudityLevel.HIGH,               # flasher: open over nothing
    # --- uniforms: render as a uniform -> MEDIUM ---
    OutfitType.NURSE_UNIFORM: NudityLevel.MEDIUM,
    OutfitType.SCHOOL_UNIFORM: NudityLevel.MEDIUM,
    OutfitType.MILITARY_UNIFORM: NudityLevel.MEDIUM,
    OutfitType.CHEF_UNIFORM: NudityLevel.MEDIUM,
    OutfitType.NAKED: NudityLevel.HIGH,
}


def outfit_exposure_cap(outfit: Optional[OutfitType]) -> NudityLevel:
    """
    The most explicit nudity level `outfit` can honestly render at (see
    OUTFIT_EXPOSURE_CAP). Unmapped/None -> MEDIUM (a safe "still dressed" default);
    the coverage test in test_story_planner makes an unmapped OutfitType impossible,
    so the default only guards a None passed by a caller.
    """
    if outfit is None:
        return NudityLevel.MEDIUM
    return OUTFIT_EXPOSURE_CAP.get(outfit, NudityLevel.MEDIUM)


# ---------------------------------------------------------------------------
# Wardrobe-style tags (WS-B trait profiles) — every garment's "style DNA".
# ---------------------------------------------------------------------------
# A character's TraitProfile carries wardrobe_styles (WardrobeStyleType); this map
# turns those abstract styles into a concrete garment SET (outfits_for_styles), which
# the trait-profile merge folds into BatchControls.wardrobe_outfits so the planner
# SOFT-biases her batches toward clothes that fit her taste (a strong bias, NOT a hard
# filter — see story_planner._prefer_wardrobe: intersect-with-fallback, never empties).
#
# Rules (coverage-tested in test_outfit_vocab_traits):
#   * EVERY OutfitType except NAKED is tagged with >=1 WardrobeStyleType (NAKED is
#     nudity, not a wardrobe taste, so it is deliberately ABSENT here just as it is
#     from favorite_outfits/never_wears).
#   * The four uniforms are tagged `professional` for DISPLAY/derivation completeness,
#     but the planner NEVER style-filters them out — _prefer_wardrobe always retains
#     _UNIFORM_OUTFITS so a nurse's work chapter keeps its uniform regardless of her
#     wardrobe styles.
# Tags describe the garment's expressed vibe, so a sporty/streetwear character and an
# elegant/glamorous one draw visibly different wardrobes from the same beat pools.
OUTFIT_STYLE_TAGS: Dict[OutfitType, frozenset] = {
    # --- dresses & gowns ---
    OutfitType.RED_EVENING_GOWN: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS}),
    OutfitType.LITTLE_BLACK_DRESS: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS}),
    OutfitType.WHITE_SUMMER_DRESS: frozenset({WardrobeStyleType.GIRLY, WardrobeStyleType.BOHEMIAN}),
    OutfitType.FLORAL_MAXI_DRESS: frozenset({WardrobeStyleType.BOHEMIAN, WardrobeStyleType.GIRLY}),
    OutfitType.COCKTAIL_DRESS: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.ELEGANT}),
    OutfitType.BODYCON_DRESS: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.EDGY}),
    OutfitType.VELVET_DRESS: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS}),
    OutfitType.SATIN_SLIP_DRESS: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.ELEGANT}),
    OutfitType.JUMPSUIT: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.EDGY}),
    OutfitType.POLKA_DOT_DRESS_50S: frozenset({WardrobeStyleType.GIRLY}),
    # --- tailored / formal ---
    OutfitType.BUSINESS_SUIT: frozenset({WardrobeStyleType.PROFESSIONAL, WardrobeStyleType.ELEGANT}),
    OutfitType.BLAZER_TROUSERS: frozenset({WardrobeStyleType.PROFESSIONAL, WardrobeStyleType.CASUAL_MINIMAL}),
    OutfitType.PENCIL_SKIRT_SET: frozenset({WardrobeStyleType.PROFESSIONAL, WardrobeStyleType.ELEGANT}),
    OutfitType.TUXEDO: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.GLAMOROUS}),
    OutfitType.POWER_SUIT_80S: frozenset({WardrobeStyleType.PROFESSIONAL, WardrobeStyleType.GLAMOROUS}),
    # --- casual / street ---
    OutfitType.DENIM_JACKET_JEANS: frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.STREETWEAR}),
    OutfitType.GRAPHIC_TEE_SHORTS: frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.STREETWEAR}),
    OutfitType.HOODIE_JOGGERS: frozenset({WardrobeStyleType.COZY_LOUNGE, WardrobeStyleType.STREETWEAR}),
    OutfitType.FLANNEL_SHIRT: frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.COZY_LOUNGE}),
    OutfitType.CROP_TOP_CARGO: frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.EDGY}),
    OutfitType.OVERSIZED_STREETWEAR: frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.EDGY}),
    OutfitType.BOMBER_JACKET_FIT: frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.EDGY}),
    OutfitType.BELL_BOTTOMS_70S: frozenset({WardrobeStyleType.BOHEMIAN, WardrobeStyleType.STREETWEAR}),
    # --- activewear ---
    OutfitType.YOGA_OUTFIT: frozenset({WardrobeStyleType.SPORTY}),
    OutfitType.TENNIS_OUTFIT: frozenset({WardrobeStyleType.SPORTY, WardrobeStyleType.GIRLY}),
    OutfitType.RUNNING_GEAR: frozenset({WardrobeStyleType.SPORTY}),
    OutfitType.GYM_SET: frozenset({WardrobeStyleType.SPORTY}),
    # --- swim ---
    OutfitType.ONE_PIECE_SWIMSUIT: frozenset({WardrobeStyleType.SPORTY, WardrobeStyleType.ELEGANT}),
    OutfitType.BIKINI: frozenset({WardrobeStyleType.SPORTY, WardrobeStyleType.GLAMOROUS}),
    # --- outerwear ---
    OutfitType.LEATHER_JACKET: frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.STREETWEAR}),
    OutfitType.TRENCH_COAT: frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.PROFESSIONAL}),
    OutfitType.PUFFER_JACKET: frozenset({WardrobeStyleType.SPORTY, WardrobeStyleType.CASUAL_MINIMAL}),
    OutfitType.FUR_COAT: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.ELEGANT}),
    # --- traditional drapes ---
    OutfitType.KIMONO: frozenset({WardrobeStyleType.TRADITIONAL, WardrobeStyleType.ELEGANT}),
    OutfitType.SARI: frozenset({WardrobeStyleType.TRADITIONAL, WardrobeStyleType.ELEGANT}),
    OutfitType.CHEONGSAM: frozenset({WardrobeStyleType.TRADITIONAL, WardrobeStyleType.ELEGANT}),
    OutfitType.HANBOK: frozenset({WardrobeStyleType.TRADITIONAL, WardrobeStyleType.GIRLY}),
    OutfitType.DIRNDL: frozenset({WardrobeStyleType.TRADITIONAL, WardrobeStyleType.GIRLY}),
    # --- eveningwear / lingerie / loungewear ---
    OutfitType.SEQUIN_TOP_SKIRT: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.GIRLY}),
    OutfitType.SILK_PAJAMAS: frozenset({WardrobeStyleType.COZY_LOUNGE, WardrobeStyleType.GIRLY}),
    OutfitType.LACE_BODYSUIT: frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.EDGY}),
    OutfitType.SATIN_ROBE: frozenset({WardrobeStyleType.COZY_LOUNGE, WardrobeStyleType.GLAMOROUS}),
    # --- uniforms: tagged professional for DISPLAY only; planner-filter-EXEMPT
    #     (story_planner._prefer_wardrobe always retains _UNIFORM_OUTFITS) ---
    OutfitType.NURSE_UNIFORM: frozenset({WardrobeStyleType.PROFESSIONAL}),
    OutfitType.SCHOOL_UNIFORM: frozenset({WardrobeStyleType.PROFESSIONAL}),
    OutfitType.MILITARY_UNIFORM: frozenset({WardrobeStyleType.PROFESSIONAL}),
    OutfitType.CHEF_UNIFORM: frozenset({WardrobeStyleType.PROFESSIONAL}),
}


def _coerce_wardrobe_styles(styles) -> Set[WardrobeStyleType]:
    """
    Coerce a list/set of WardrobeStyleType-or-raw-values to a set of
    WardrobeStyleType. Tolerant: raw string values are coerced, unknowns skipped,
    None/empty -> empty set. Shared by outfits_for_styles and the generation-pool
    wardrobe filter so both accept the same loose inputs.
    """
    wanted: Set[WardrobeStyleType] = set()
    for s in (styles or []):
        if isinstance(s, WardrobeStyleType):
            wanted.add(s)
        else:
            try:
                wanted.add(WardrobeStyleType(getattr(s, "value", s)))
            except (ValueError, TypeError):
                continue
    return wanted


def outfits_for_styles(styles) -> Set[OutfitType]:
    """
    Every OutfitType whose OUTFIT_STYLE_TAGS intersect `styles` (a list/set of
    WardrobeStyleType or their values). Empty/None styles -> empty set (no bias).
    NAKED is never returned (absent from OUTFIT_STYLE_TAGS). Tolerant of raw string
    values so a stored/LLM style survives; unknown styles are skipped.
    """
    wanted = _coerce_wardrobe_styles(styles)
    if not wanted:
        return set()
    return {o for o, tags in OUTFIT_STYLE_TAGS.items() if tags & wanted}


# ---------------------------------------------------------------------------
# Outfit keyword phrases (WS-B) — the like/dislike matching vocabulary per garment.
# ---------------------------------------------------------------------------
# VALUE-keyed (OutfitType.value -> phrase), exactly like scene_vocab.LOCATION_PHRASES,
# so it can be passed straight to story_planner._weighted_pick as a phrase_map: a like
# of "silk" or "gala" now boosts the right garments, and a dislike softly excludes them,
# by matching real garment NOUNS / FABRICS / OCCASION words instead of only the enum name.
#
# DELIBERATELY NOT the graded OUTFIT_DESCRIPTIONS tier prose: that prose is full of
# generic words ("black", "tight", "fitted", "short") that would false-match unrelated
# likes/dislikes — the canonical failure the plan calls out is a dislike "black coffee"
# nuking little_black_dress. So these phrases carry only DISTINCTIVE garment nouns,
# fabrics and vibe words, and never a bare color/fit adjective standing alone.
# Coverage-tested: every OutfitType value (incl. naked) has a non-empty phrase.
OUTFIT_KEYWORD_PHRASES: Dict[str, str] = {
    # dresses & gowns
    "red_evening_gown": "gown formal gala chiffon silk glamour",
    "little_black_dress": "chic evening minimalist crepe timeless",
    "white_summer_dress": "sundress summer floaty cotton breezy linen",
    "floral_maxi_dress": "floral maxi bohemian boho flowy chiffon",
    "cocktail_dress": "cocktail sequined shimmer party glam",
    "bodycon_dress": "bodycon bandage clubwear sleek stretch",
    "velvet_dress": "velvet plush evening lush soft",
    "satin_slip_dress": "slip satin silky camisole nightgown lingerie",
    "jumpsuit": "jumpsuit romper sleek modern",
    "polka_dot_dress_50s": "polka dot retro vintage swing pinup fifties",
    # tailored / formal
    "business_suit": "suit tailored blazer corporate office pinstripe",
    "blazer_trousers": "blazer trousers smart office workwear",
    "pencil_skirt_set": "pencil skirt blouse secretary office prim",
    "tuxedo": "tuxedo satin lapel formal eveningwear",
    "power_suit_80s": "powersuit eighties bold shoulderpads retro",
    # casual / street
    "denim_jacket_jeans": "denim jeans jacket casual everyday",
    "graphic_tee_shorts": "tee tshirt shorts casual playful denim",
    "hoodie_joggers": "hoodie joggers cozy loungewear athleisure sweats",
    "flannel_shirt": "flannel plaid shirt cozy rustic casual",
    "crop_top_cargo": "crop top cargo utility streetwear sporty",
    "oversized_streetwear": "streetwear oversized baggy urban",
    "bomber_jacket_fit": "bomber jacket streetwear casual sporty",
    "bell_bottoms_70s": "bellbottoms flares seventies retro boho groovy",
    # active
    "yoga_outfit": "yoga leggings sportsbra activewear athletic stretch",
    "tennis_outfit": "tennis skirt polo preppy sporty athletic",
    "running_gear": "running athletic activewear jogging sporty compression",
    "gym_set": "gym sportsbra workout activewear athletic fitness",
    # swim
    "one_piece_swimsuit": "swimsuit onepiece swim beach pool",
    "bikini": "bikini swim beach poolside string",
    # outerwear
    "leather_jacket": "leather biker moto edgy rocker",
    "trench_coat": "trench coat belted classic tailored",
    "puffer_jacket": "puffer padded quilted winter cozy outdoor",
    "fur_coat": "fur coat luxe glamour opulent plush",
    # traditional
    "kimono": "kimono silk robe traditional japanese obi",
    "sari": "sari drape traditional indian silk",
    "cheongsam": "cheongsam qipao silk traditional mandarin",
    "hanbok": "hanbok traditional korean chima jeogori",
    "dirndl": "dirndl bodice traditional bavarian laced",
    # eveningwear / lingerie / loungewear
    "sequin_top_skirt": "sequin sparkle glitter party clubwear",
    "silk_pajamas": "pajamas silk loungewear sleepwear cozy pyjamas",
    "lace_bodysuit": "lace bodysuit lingerie sheer delicate",
    "satin_robe": "robe satin silky boudoir lounge",
    # uniforms
    "nurse_uniform": "nurse scrubs medical uniform",
    "school_uniform": "schoolgirl uniform pleated preppy academic",
    "military_uniform": "military uniform officer service",
    "chef_uniform": "chef whites culinary kitchen uniform",
    # nudity (never in a pick pool; present so every OutfitType value is covered)
    "naked": "nude bare undressed skin",
}


# ---------------------------------------------------------------------------
# Nude-base body description (per-character neutral anatomical reference asset)
#
# NOT a scene: the nude base is the neutral, once-per-character source image that
# every story-batch scene is later dressed on top of, so it must read as a calm
# anatomical reference, NOT the arousal-styled NAKED/HIGH tier prose above ("hard
# nipples, swollen aroused pussy lips…" is wrong for a neutral base). Selected by
# build_prompt (api/v1/endpoints/outfit.py) when outfitPromptMode == "nude_base".
# The skin-tone anchor is deliberately RELATIVE ("matches her face and neck") so a
# dark-skinned character is not silently pushed lighter toward an absolute tone.
NUDE_BASE_BODY_DESCRIPTION = (
    "completely nude in a relaxed neutral standing stance, arms resting naturally "
    "at her sides, natural matte skin with clearly visible pores and fine texture, "
    "no oil or shine on the skin, an even natural skin tone that exactly matches "
    "her face and neck, body in a calm neutral non-aroused state, a plain neutral "
    "full-body reference"
)


# ---------------------------------------------------------------------------
# Accessories Mapping
# ---------------------------------------------------------------------------
ACCESSORY_DESCRIPTIONS: Dict[AccessoryType, str] = {
    AccessoryType.NECKLACE: "wearing an elegant necklace",
    AccessoryType.EARRINGS: "wearing stylish earrings",
    AccessoryType.GLASSES: "wearing fashionable glasses",
    AccessoryType.HAT: "wearing a stylish hat",
    AccessoryType.SUNGLASSES: "wearing trendy sunglasses",
}


# ---------------------------------------------------------------------------
# Generation-side clothing clause
#
# The character-generation base model is NSFW-tuned, so with no clothing token
# and no nude-suppression it renders nude by default. These helpers produce a
# declarative clothing clause (and a matching negative-side suppression, see
# services.prompt_constants.nudity_suppression) so the requested nudity level is
# actually honored.
# ---------------------------------------------------------------------------

# Neutral fallback clothing clauses when the admin picks a nudity level but no
# specific outfit. Keeps generation dressed-by-default at LOW.
# LEGACY single-string map: used verbatim when variety is OFF (variety_seed=None),
# so the kill-switch path stays byte-identical to the pre-WS3 behavior.
_GENERATION_DEFAULT_CLOTHING: Dict[NudityLevel, str] = {
    NudityLevel.LOW: "fully clothed in a stylish, well-fitted outfit",
    NudityLevel.SUGGESTIVE: "in a stylish, well-fitted outfit with a teasing hint of skin at the neckline or hem",
    NudityLevel.MEDIUM: "in a revealing, partially-exposed outfit that bares some skin",
    NudityLevel.REVEALING: "in a scarcely-there outfit, mostly undone and barely covering, most of her body exposed",
    NudityLevel.HIGH: "nude, bare skin on display",
}

# WS3 default-outfit POOLS: when variety is ON and no specific outfit is chosen, a
# seeded pick from the level's pool dresses each (batch) card in a different
# concrete, everyday-real garment (garment + color + fabric) instead of the vague
# legacy single string, so a batch stops rendering the same outfit N times. No
# studio/glamour/editorial/photoshoot language (that claims its own look). HIGH is
# a single "bare" entry (kept as today — a nude request has nothing to vary).
_GENERATION_DEFAULT_CLOTHING_POOL: Dict[NudityLevel, List[str]] = {
    NudityLevel.LOW: [
        "wearing a rust-orange ribbed knit sweater and high-waisted blue jeans",
        "in a white linen button-up shirt tucked into tailored black trousers",
        "wearing a forest-green wrap blouse and beige slacks",
        "in a soft grey oversized cardigan over a fitted cream tee and dark jeans",
        "wearing a burgundy turtleneck and a pleated camel midi skirt",
        "in a chambray denim shirt dress belted at the waist, hem at the knee",
    ],
    NudityLevel.SUGGESTIVE: [
        "wearing a fitted black ribbed top with a scooped neckline and high-waisted jeans",
        "in a silky mauve wrap blouse loosely knotted at the waist and slim tailored trousers",
        "wearing a soft off-the-shoulder oatmeal knit sweater and a short denim skirt",
        "in a cropped fitted white tee baring a sliver of midriff and low-rise jeans",
        "wearing a snug rust henley with the top buttons undone and skinny jeans",
        "in a clingy ribbed olive midi dress with a modest side slit at the hem",
    ],
    NudityLevel.MEDIUM: [
        "in an unbuttoned oversized chambray shirt over a lace bralette, midriff bare",
        "wearing a deep-cut satin cami with no bra and low-slung cotton shorts",
        "in a sheer black mesh long-sleeve top over a bralette, midriff bare",
        "wearing a loosely tied short robe slipping to show cleavage and thigh",
        "in a cropped tank pushed up under the bust with unbuttoned denim shorts",
    ],
    NudityLevel.REVEALING: [
        "in a barely-tied silk robe hanging open over bare skin, mostly exposed",
        "wearing only an unbuttoned oversized shirt slipping off one shoulder, little underneath",
        "in a sheer slip pushed off both shoulders, clinging and see-through",
        "wearing only a thong and an open shirt that covers almost nothing",
        "in a loosely draped sheet slipping low off the body, most of her skin bare",
    ],
    NudityLevel.HIGH: [
        "nude, bare skin on display",
    ],
}

# WS-B style tags for the generation default-clothing POOL, INDEX-ALIGNED with
# _GENERATION_DEFAULT_CLOTHING_POOL entry-for-entry (same keys, same list lengths).
# Phase B3 will use these to filter the seeded generation pool by a character's
# wardrobe_styles (empty filter -> full pool); authored here now so the alignment is
# coverage-tested alongside the pool it mirrors. Each frozenset is the style DNA of the
# concrete outfit at the SAME index; the single HIGH "nude" entry has no wardrobe style
# (empty set). Do NOT reorder either list without updating the other — the test fails.
_GENERATION_POOL_STYLE_TAGS: Dict[NudityLevel, List[frozenset]] = {
    NudityLevel.LOW: [
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.COZY_LOUNGE}),   # ribbed knit sweater + jeans
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.PROFESSIONAL}),  # white linen shirt + trousers
        frozenset({WardrobeStyleType.PROFESSIONAL, WardrobeStyleType.CASUAL_MINIMAL}),  # wrap blouse + slacks
        frozenset({WardrobeStyleType.COZY_LOUNGE, WardrobeStyleType.CASUAL_MINIMAL}),   # oversized cardigan + tee + jeans
        frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.CASUAL_MINIMAL}),       # turtleneck + camel midi skirt
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.STREETWEAR}),    # chambray shirt dress
    ],
    NudityLevel.SUGGESTIVE: [
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.EDGY}),          # fitted ribbed top + jeans
        frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.PROFESSIONAL}),         # silky wrap blouse + trousers
        frozenset({WardrobeStyleType.GIRLY, WardrobeStyleType.CASUAL_MINIMAL}),         # off-shoulder knit + denim skirt
        frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.CASUAL_MINIMAL}),    # cropped tee + low-rise jeans
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.STREETWEAR}),    # rust henley + skinny jeans
        frozenset({WardrobeStyleType.ELEGANT, WardrobeStyleType.CASUAL_MINIMAL}),       # clingy ribbed midi dress
    ],
    NudityLevel.MEDIUM: [
        frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.STREETWEAR}),              # chambray shirt over bralette
        frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.COZY_LOUNGE}),        # satin cami + shorts
        frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.GLAMOROUS}),               # sheer mesh top over bralette
        frozenset({WardrobeStyleType.COZY_LOUNGE, WardrobeStyleType.GLAMOROUS}),        # loosely tied short robe
        frozenset({WardrobeStyleType.STREETWEAR, WardrobeStyleType.CASUAL_MINIMAL}),    # cropped tank + denim shorts
    ],
    NudityLevel.REVEALING: [
        frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.COZY_LOUNGE}),        # barely-tied silk robe
        frozenset({WardrobeStyleType.CASUAL_MINIMAL, WardrobeStyleType.EDGY}),          # unbuttoned oversized shirt
        frozenset({WardrobeStyleType.GLAMOROUS, WardrobeStyleType.ELEGANT}),            # sheer slip
        frozenset({WardrobeStyleType.EDGY, WardrobeStyleType.GLAMOROUS}),               # thong + open shirt
        frozenset({WardrobeStyleType.GLAMOROUS}),                                       # loosely draped sheet
    ],
    NudityLevel.HIGH: [
        frozenset(),                                                                    # nude — no wardrobe style
    ],
}

# WS3 positive coverage guard, appended to the default clothing clause at modest
# levels only. Negatives are inert at cfg=1, so coverage has to be asserted with
# POSITIVE tokens or a "low" request drifts toward exposure on the NSFW base.
# LOW/SUGGESTIVE only; MEDIUM+ are meant to expose, so no guard there.
_GENERATION_COVERAGE_GUARD: Dict[NudityLevel, str] = {
    NudityLevel.LOW: ", modest neckline, shoulders and midriff covered",
    NudityLevel.SUGGESTIVE: ", covered except a hint of cleavage",
}


def accessories_clause(accessories: Optional[List[AccessoryType]]) -> str:
    """Comma-joined accessory phrases, or '' when none."""
    if not accessories:
        return ""
    return ", ".join(
        ACCESSORY_DESCRIPTIONS.get(acc, str(getattr(acc, "value", acc)))
        for acc in accessories
    )


def _wardrobe_filter_pool(
    pool: List[str], nudity_level: NudityLevel, wardrobe_styles
) -> List[str]:
    """
    (WS-B / B3) Bias a default-clothing POOL toward a character's wardrobe_styles.

    Returns the SUBSET of `pool` whose index-aligned _GENERATION_POOL_STYLE_TAGS
    entry overlaps `wardrobe_styles`. Returns the ORIGINAL pool object UNCHANGED when:
      * wardrobe_styles is empty/None (parity: the caller's single seeded .choice
        draw then stays byte-identical to the no-wardrobe path — enforced by tests);
      * the tag list is missing or length-misaligned with the pool (defensive);
      * the filter would remove every entry (empty result -> full pool).
    Exactly one .choice draw happens in the caller regardless, so rng use is
    unchanged — only the LIST it draws from narrows.
    """
    wanted = _coerce_wardrobe_styles(wardrobe_styles)
    if not wanted:
        return pool
    tags = _GENERATION_POOL_STYLE_TAGS.get(nudity_level)
    if not tags or len(tags) != len(pool):
        return pool
    filtered = [entry for entry, fs in zip(pool, tags) if fs & wanted]
    return filtered or pool


def generation_outfit_clause(
    outfit: Optional[OutfitType] = None,
    nudity_level: NudityLevel = NudityLevel.LOW,
    accessories: Optional[List[AccessoryType]] = None,
    variety_seed: Optional[int] = None,
    wardrobe_styles=None,
) -> str:
    """
    Declarative clothing clause for a character-generation prompt.

    * A specific outfit -> "wearing <graded description>" at the chosen level.
    * OutfitType.NAKED   -> the graded NAKED description verbatim (no "wearing").
    * No outfit          -> a neutral clothed/partly-clothed/nude fallback so the
                            character is never silently left for the model to
                            default to nudity. With ``variety_seed`` set, a seeded
                            pick from the level's pool (concrete garment, so batch
                            cards differ) plus a positive coverage guard at
                            LOW/SUGGESTIVE; with ``variety_seed`` None, the legacy
                            single string (byte-identical to pre-WS3).

    ``wardrobe_styles`` (WS-B / B3, a character's WardrobeStyleType list) only
    matters on the seeded no-explicit-outfit pool path: it narrows the level's pool
    to entries whose style tags overlap, so a sporty character draws sporty default
    clothing. Still EXACTLY one seeded .choice draw; an empty/None value (or a filter
    that matches nothing) leaves the draw byte-identical to today. Ignored when a
    specific outfit is given or variety is off.
    Accessories are appended when present.
    """
    if outfit == OutfitType.NAKED:
        levels = OUTFIT_DESCRIPTIONS.get(OutfitType.NAKED, {})
        clause = levels.get(nudity_level, levels.get(NudityLevel.HIGH, "completely nude"))
    elif outfit is not None:
        levels = OUTFIT_DESCRIPTIONS.get(outfit)
        if levels:
            desc = levels.get(nudity_level, levels[NudityLevel.LOW])
        else:
            desc = str(getattr(outfit, "value", outfit)).replace("_", " ")
        clause = f"wearing {desc}"
    elif variety_seed is not None:
        pool = _GENERATION_DEFAULT_CLOTHING_POOL.get(
            nudity_level, _GENERATION_DEFAULT_CLOTHING_POOL[NudityLevel.LOW]
        )
        pool = _wardrobe_filter_pool(pool, nudity_level, wardrobe_styles)
        clause = random.Random(variety_seed).choice(pool)
        clause += _GENERATION_COVERAGE_GUARD.get(nudity_level, "")
    else:
        clause = _GENERATION_DEFAULT_CLOTHING.get(
            nudity_level, _GENERATION_DEFAULT_CLOTHING[NudityLevel.LOW]
        )

    acc = accessories_clause(accessories)
    return f"{clause}, {acc}" if acc else clause
