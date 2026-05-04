"""
SIIL PRODUCT COLOR CONSTANTS
==============================
HARDLOCKED hex codes sampled directly from official product reference photos.
DO NOT CHANGE these values unless working from new official packshot photography.

Sampling methodology:
  - Black wrap  : pixel scan of Gracia_basic_black.jpg, y=60-73%, x=40-65% (dark band)
  - Beige wrap  : visual comparison Gracia_basic_beige.jpg + Gracia_basic_black.jpg
  - Belt colors : Tara/Sara studio reference photos + Product Closeup images
  - MIA cream   : Product Closeup - Ostomy Wrap MIA (Cream) (1).jpg center sample

Use PRODUCT_COLORS[product][color] in all generation scripts.
"""

# ── SIIL BASIC WRAP (OSTOMY WRAP) ────────────────────────────────────────────
WRAP_BASIC = {
    "Black": {
        "hex": "#212121",           # Deep matte near-black. Sampled px: RGB(33,33,33)
        "prompt_color": "DEEP MATTE BLACK (#212121) — smooth, flat, zero-sheen stretch fabric. The darkest possible near-black, no navy tint. Rich true black.",
        "short": "deep matte black",
    },
    "Beige": {
        "hex": "#C9A882",           # Warm sandy camel / natural nude. Sampled from Gracia_basic_beige.jpg
        "prompt_color": "WARM SANDY CAMEL (#C9A882) — smooth matte stretch fabric. Warm neutral beige, like dry desert sand or natural linen, slightly golden undertone. NOT pink, NOT cream, NOT dark.",
        "short": "warm sandy camel beige",
    },
}

# ── SIIL OSTOMY BELT ──────────────────────────────────────────────────────────
BELT = {
    "Black": {
        "hex": "#1C1524",           # Very dark midnight navy-black. Sampled from Sara - Ostomy Belt (Black Women)
        "prompt_color": "MIDNIGHT NAVY-BLACK (#1C1524) — very dark, near-black with subtle deep navy undertone. Smooth performance stretch fabric. Essentially black.",
        "short": "midnight navy-black",
    },
    "Beige": {
        "hex": "#D4975A",           # Warm golden sand / amber-camel. Sampled from Tara - Ostomy Belt (Beige Women)
        "prompt_color": "WARM GOLDEN SAND (#D4975A) — smooth performance stretch. Warm amber-camel/sandy color, more golden than beige, like raw natural linen or warm desert sand. Has a warm earthy glow.",
        "short": "warm golden sand",
    },
    "Blue": {
        "hex": "#1B2B5A",           # Deep navy midnight blue. From Product Closeup - Ostomy Belt (Blue Women) visual
        "prompt_color": "DEEP MIDNIGHT NAVY (#1B2B5A) — smooth performance stretch. Dark, rich navy blue. Deeper than standard navy, close to midnight blue. Professional athletic navy.",
        "short": "midnight navy blue",
    },
}

# ── SIIL MIA WRAP ─────────────────────────────────────────────────────────────
WRAP_MIA = {
    "Cream": {
        "hex": "#F5E5D5",           # Soft warm ivory cream. Sampled from Product Closeup - Ostomy Wrap MIA (Cream) (1).jpg
        "prompt_color": "WARM IVORY CREAM (#F5E5D5) — smooth matte stretch fabric. Very soft, light warm cream — like eggshell or natural unbleached cotton. Slightly warm/peach undertone. NOT white, NOT yellow.",
        "short": "warm ivory cream",
    },
}

# ── CONSOLIDATED LOOKUP ───────────────────────────────────────────────────────
PRODUCT_COLORS = {
    "Ostomy Wrap Basic":  WRAP_BASIC,
    "Ostomy Wrap MIA":    WRAP_MIA,
    "Ostomy Belt":        BELT,
}

# ── STUDIO BACKDROP COMPLEMENTS ───────────────────────────────────────────────
# Recommended backdrop colors per product color for maximum contrast + harmony
BACKDROP_FOR = {
    # Wrap Black → warm terracotta, clay, mushroom — never cold grey or white
    "Wrap Black":  ["warm TERRACOTTA CLAY (#A0614A)", "warm MUSHROOM STONE (#9E8A7A)", "warm SAND (#C8AA8A)"],
    # Wrap Beige → terracotta, sage, dusty rose — create contrast against nude
    "Wrap Beige":  ["TERRACOTTA (#9A5C46)", "SAGE MIST (#8A9A7E)", "DUSTY MAUVE (#9A7A82)"],
    # Belt Black → same warm rules as Wrap Black
    "Belt Black":  ["warm TERRACOTTA CLAY (#A0614A)", "warm MUSHROOM (#9E8A7A)", "WARM STONE (#B0987A)"],
    # Belt Beige → teal, slate, sage for contrast against warm sand
    "Belt Beige":  ["DEEP TEAL (#2A6B72)", "SLATE GREY (#6A7480)", "SAGE GREEN (#6A8060)"],
    # Belt Blue  → warm terracotta, cream, sandy for warmth against navy
    "Belt Blue":   ["WARM TERRACOTTA (#A0614A)", "WARM SAND (#C8AA8A)", "IVORY CREAM (#F5E4D0)"],
}


def get_wrap_prompt(color: str) -> str:
    """Return the hardlocked color description for use in generation prompts."""
    c = WRAP_BASIC.get(color)
    if not c:
        raise ValueError(f"Unknown wrap color: {color!r}. Valid: {list(WRAP_BASIC)}")
    return c["prompt_color"]


def get_belt_prompt(color: str) -> str:
    c = BELT.get(color)
    if not c:
        raise ValueError(f"Unknown belt color: {color!r}. Valid: {list(BELT)}")
    return c["prompt_color"]


# ── USAGE EXAMPLE ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("SIIL Product Color Registry")
    print("=" * 50)
    for product, colors in PRODUCT_COLORS.items():
        print(f"\n{product}:")
        for color_name, data in colors.items():
            print(f"  {color_name:10s}  {data['hex']}  ->  {data['short']}")

    print("\n\nWrap prompt examples:")
    print(f"  Black: {get_wrap_prompt('Black')}")
    print(f"  Beige: {get_wrap_prompt('Beige')}")
