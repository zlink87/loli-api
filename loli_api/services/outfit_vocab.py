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
               real exposure (cleavage, sideboob, underboob).
  * REVEALING  mostly undone or displaced: garment barely covering, one or
               both breasts exposed or fully sheer, bottoms pushed aside or
               pulled down but not removed — more exposed than MEDIUM, short
               of HIGH's full explicitness.
  * HIGH       explicit.
Exposure is strictly opt-in past LOW; a LOW-nudity request must never render
a costume that is secretly half-undressed.
"""
from typing import Dict, List, Optional

from models.enums import OutfitType, AccessoryType, NudityLevel


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
        NudityLevel.MEDIUM: "a thin white summer dress that hints at the silhouette underneath in bright light, no bra so the shape of nipples is faintly visible, hem fluttering above the knees",
        NudityLevel.REVEALING: "a sheer white summer dress that turns see-through in direct light, no bra so the outline of her nipples shows plainly through the fabric, hem riding up to the tops of the thighs",
        NudityLevel.HIGH: "a whisper-thin, almost transparent white summer dress that turns completely see-through in light, no bra or panties so hard nipples and the dark triangle of pubic hair are clearly visible, hem fluttering just below the curve of the ass",
    },
    OutfitType.FLORAL_MAXI_DRESS: {
        NudityLevel.LOW: "a flowing floral wrap maxi dress cinched with a tie at the waist, soft fabric moving gracefully with each step",
        NudityLevel.SUGGESTIVE: "a flowing floral wrap maxi dress with the tie loosened at the waist, wrap gaping slightly at the chest to show a hint of cleavage, soft fabric moving gracefully with each step",
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
        NudityLevel.MEDIUM: "a tailored black business suit with blazer unbuttoned over a sheer blouse, deep cleavage visible, trousers fitted tightly around hips",
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
        NudityLevel.MEDIUM: "a champagne satin slip dress with thin straps, fabric clinging to curves, short hem showing thighs, nipples hinted through the satin",
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
        NudityLevel.MEDIUM: "a sheer black lace bodysuit with strategic coverage, nipples and skin visible through the lace pattern, hugging every curve",
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
_GENERATION_DEFAULT_CLOTHING: Dict[NudityLevel, str] = {
    NudityLevel.LOW: "fully clothed in a stylish, well-fitted outfit",
    NudityLevel.SUGGESTIVE: "in a stylish, well-fitted outfit with a teasing hint of skin at the neckline or hem",
    NudityLevel.MEDIUM: "in a revealing, partially-exposed outfit that bares some skin",
    NudityLevel.REVEALING: "in a scarcely-there outfit, mostly undone and barely covering, most of her body exposed",
    NudityLevel.HIGH: "nude, bare skin on display",
}


def accessories_clause(accessories: Optional[List[AccessoryType]]) -> str:
    """Comma-joined accessory phrases, or '' when none."""
    if not accessories:
        return ""
    return ", ".join(
        ACCESSORY_DESCRIPTIONS.get(acc, str(getattr(acc, "value", acc)))
        for acc in accessories
    )


def generation_outfit_clause(
    outfit: Optional[OutfitType] = None,
    nudity_level: NudityLevel = NudityLevel.LOW,
    accessories: Optional[List[AccessoryType]] = None,
) -> str:
    """
    Declarative clothing clause for a character-generation prompt.

    * A specific outfit -> "wearing <graded description>" at the chosen level.
    * OutfitType.NAKED   -> the graded NAKED description verbatim (no "wearing").
    * No outfit          -> a neutral clothed/partly-clothed/nude fallback so the
                            character is never silently left for the model to
                            default to nudity.
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
    else:
        clause = _GENERATION_DEFAULT_CLOTHING.get(
            nudity_level, _GENERATION_DEFAULT_CLOTHING[NudityLevel.LOW]
        )

    acc = accessories_clause(accessories)
    return f"{clause}, {acc}" if acc else clause
