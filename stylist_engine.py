
"""AI Personal Stylist engine for v14.

The engine creates three coordinated looks from customer choices and a styling context.
It deliberately treats fashion advice as suggestions, not objective truths.
"""

COLOR_FAMILIES = {
    "neutrals": ["black","white","cream","ivory","beige","camel","tan","taupe","grey","charcoal","navy","brown"],
    "earth": ["olive","forest green","sage","rust","terracotta","mustard","chocolate","burgundy"],
    "cool": ["sky blue","powder blue","cobalt","royal blue","teal","emerald","lavender","purple","plum","magenta"],
    "warm": ["coral","peach","orange","red","maroon","mustard","yellow","pink","hot pink"],
    "metallic": ["silver","gold","rose gold","bronze"],
}

OCCASION_RULES = {
    "Casual": {"shoes":["white sneakers","retro sneakers","canvas sneakers","loafers"], "accessories":["classic watch","sunglasses","cap","crossbody bag"]},
    "Smart Casual": {"shoes":["loafers","minimal leather sneakers","derby shoes","ballet flats"], "accessories":["classic watch","leather belt","sunglasses","structured handbag"]},
    "Formal": {"shoes":["Oxford shoes","Derby shoes","pumps","block heels"], "accessories":["dress watch","belt","cufflinks","pocket square"]},
    "Business": {"shoes":["Oxford shoes","Derby shoes","penny loafers","pumps"], "accessories":["dress watch","leather belt","structured handbag","cufflinks"]},
    "Party": {"shoes":["statement heels","platform shoes","Chelsea boots","dress shoes"], "accessories":["statement earrings","layered necklace","clutch","chronograph watch"]},
    "Festive": {"shoes":["Juttis","Mojaris","Kolhapuri sandals","strappy sandals"], "accessories":["bangles","statement earrings","pendant","clutch"]},
    "Wedding": {"shoes":["Mojaris","Juttis","block heels","strappy sandals"], "accessories":["statement earrings","bangles","clutch","brooch"]},
    "Travel": {"shoes":["running sneakers","retro sneakers","slip-on sneakers","walking sandals"], "accessories":["smartwatch","sunglasses","crossbody bag","backpack"]},
    "Date": {"shoes":["loafers","Chelsea boots","minimal leather sneakers","block heels"], "accessories":["classic watch","necklace","sunglasses","small shoulder bag"]},
}

def _first(items, default):
    return items[0] if items else default

def build_three_looks(profile):
    """Return three complete, internally consistent look suggestions."""
    top = profile.get("top_color") or "navy"
    outfit = profile.get("outfit") or "smart casual"
    occasion = profile.get("occasion") or "Casual"
    bottom = profile.get("bottom_color") or "beige"
    custom_footwear = profile.get("footwear")
    custom_accessory = profile.get("accessory")

    rule = OCCASION_RULES.get(occasion, OCCASION_RULES["Casual"])
    shoes = custom_footwear if custom_footwear and custom_footwear.lower() != "ai choose" else rule["shoes"][0]
    accessory = custom_accessory if custom_accessory and custom_accessory.lower() != "ai choose" else rule["accessories"][0]

    # Variations preserve customer-selected anchors and change supporting pieces.
    shoe2 = rule["shoes"][1] if len(rule["shoes"]) > 1 else shoes
    shoe3 = rule["shoes"][2] if len(rule["shoes"]) > 2 else shoes
    acc2 = rule["accessories"][1] if len(rule["accessories"]) > 1 else accessory
    acc3 = rule["accessories"][2] if len(rule["accessories"]) > 2 else accessory

    return [
        {"name":"Look 1 — Balanced","top_color":top,"outfit":outfit,"bottom_color":bottom,
         "footwear":shoes,"accessories":accessory,"occasion":occasion,
         "why":"Keeps your selected pieces as the anchors and coordinates the supporting items for the occasion."},
        {"name":"Look 2 — Alternate","top_color":top,"outfit":outfit,"bottom_color":bottom,
         "footwear":shoe2,"accessories":acc2,"occasion":occasion,
         "why":"Keeps the main outfit while changing the footwear and accessory direction."},
        {"name":"Look 3 — Statement","top_color":top,"outfit":outfit,"bottom_color":bottom,
         "footwear":shoe3,"accessories":acc3,"occasion":occasion,
         "why":"Uses a stronger styling accent while keeping the selected colour and outfit consistent."},
    ]

def visual_try_on_prompt(look, customer_notes=""):
    return f"""Create a realistic fashion visual try-on using the customer's uploaded reference photo.
Apply this complete look:
- Top / main colour: {look.get('top_color','')}
- Outfit/style: {look.get('outfit','')}
- Bottom colour: {look.get('bottom_color','')}
- Footwear: {look.get('footwear','')}
- Accessories: {look.get('accessories','')}
- Occasion: {look.get('occasion','')}
Customer notes: {customer_notes}

Preserve the customer's facial identity, natural body proportions, pose and overall photographic context.
Change clothing and styling only where needed. Make garments, footwear and accessories coherent with each other.
Do not invent logos, text or brand marks. Avoid changing facial features or body shape.
Render realistic fabric texture, folds, shadows and natural contact/occlusion.
This is a visual styling approximation, not a measurement or fit guarantee."""
