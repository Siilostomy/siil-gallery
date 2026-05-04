"""
SIIL GENERATION PROMPT CONSTANTS — HARDLOCKED v2
===================================================
Single source of truth for ALL image generation scripts.
These rules are PERMANENT and must be imported into every generator.

Key hardcoded mandates (2026-05-04):
  1. FOOTWEAR — bare feet (studio) or sport shoes (running). No flip-flops ever.
  2. TOP VARIETY — cycled rotation, never repeat same silhouette consecutively.
  3. BACKDROP — warm neutrals only. No white. No hospital lights. No dark.
  4. DEPRECATED MODELS — Gracia is NOT generated as a new campaign model.
     Her portrait is in model_refs/ only for regenning existing gallery images.
"""

from __future__ import annotations
import hashlib

# ─────────────────────────────────────────────────────────────────────────────
# 1. FOOTWEAR — HARDLOCKED
# ─────────────────────────────────────────────────────────────────────────────

FOOTWEAR_STUDIO = (
    "BARE FEET — no shoes, no slippers, no sandals, no flip-flops, no socks. "
    "Feet are naturally bare and clean, toenails neat. "
    "This is mandatory for all studio shots."
)

FOOTWEAR_RUNNING = (
    "FOOTWEAR: proper athletic running shoes — e.g. white minimalist trainers, "
    "neutral performance sneakers — laced and fitted. "
    "STRICTLY NO flip-flops, NO sandals, NO bare feet for running scenes."
)

FOOTWEAR_LIFESTYLE_CASUAL = (
    "FOOTWEAR: clean white sneakers, leather sandals, or barefoot depending on "
    "scene (beach=barefoot, city=sneakers, yoga=barefoot). "
    "NEVER flip-flops."
)

FOOTWEAR_NO_FLIPFLOPS = (
    "⚠ CRITICAL FOOTWEAR RULE: NEVER generate flip-flops or thong sandals under "
    "any circumstances. They are permanently prohibited in all SIIL imagery."
)


# ─────────────────────────────────────────────────────────────────────────────
# 2. TOP VARIETY ROTATION — HARDLOCKED
# ─────────────────────────────────────────────────────────────────────────────
# 24 distinct silhouettes. The rotation function ensures no two adjacent shots
# share the same style. Pass shot_index to get_top().

TOPS_ROTATION = [
    # (silhouette_key, full_description)
    ("ribbed_tank_thin",    "fitted RIBBED COTTON cropped sleeveless tank, thin spaghetti straps, scoop neckline"),
    ("smooth_cami",         "smooth SILK-TOUCH cropped camisole, delicate thin straps, draped front"),
    ("short_sleeve_round",  "fitted RIBBED COTTON cropped short-sleeve top, clean round neckline"),
    ("long_sleeve_fitted",  "fitted RIBBED KNIT cropped long-sleeve top, clean crew neckline, close-fitting sleeves"),
    ("sports_bra_minimal",  "minimalist SPORTS BRA crop, clean straight neckline, thick supportive straps"),
    ("linen_button_front",  "cropped LINEN button-front shirt, half-unbuttoned, tied loosely at the hem"),
    ("bralette_soft",       "soft COTTON bralette, wide fabric band, minimal coverage, natural texture"),
    ("turtleneck_crop",     "slim-fit RIBBED TURTLENECK cropped top, close to body, clean neck"),
    ("racer_back",          "RACERBACK cropped athletic top, thin straps meeting at a racer point on back"),
    ("wide_strap_tank",     "wide-strap COTTON cropped tank, relaxed fit, generous strap width, scoop neckline"),
    ("mesh_overlay",        "MESH cropped long-sleeve top over a smooth sports bra, subtle texture"),
    ("wrap_front",          "wrap-front CROPPED top, self-tie at side, V-neckline, short sleeves"),
    ("knit_crop_halter",    "knit HALTER crop top, self-tie at nape, open back, clean front"),
    ("boat_neck_crop",      "fitted BOAT-NECK cropped short-sleeve top, wide elegant neckline"),
    ("cutout_shoulder",     "cropped top with subtle CUTOUT at one shoulder, otherwise clean and fitted"),
    ("off_shoulder",        "soft OFF-SHOULDER cropped top, elasticated neckline, relaxed draped style"),
    ("square_neck_crop",    "fitted SQUARE-NECK cropped camisole, structured neckline, thin straps"),
    ("asymmetric_hem",      "fitted ASYMMETRIC-HEM cropped top, one side slightly longer, short sleeve"),
    ("mock_neck_short",     "slim MOCK-NECK cropped short-sleeve top, snug fit, minimal styling"),
    ("crop_blazer_open",    "CROPPED BLAZER worn open over a simple crop cami — relaxed editorial feel"),
    ("athletic_crop_zip",   "ATHLETIC cropped top with subtle quarter-zip at neckline, performance fabric"),
    ("french_terry_crop",   "relaxed FRENCH TERRY cropped sweatshirt, raw hem, slightly oversized"),
    ("body_suit_scoop",     "FITTED SCOOP-NECK bodysuit (appears as cropped top when tucked)"),
    ("stripe_crop",         "fitted STRIPED cropped top, fine horizontal stripes, short sleeve, crew neck"),
]

# Approved colors per top (cycle through to avoid all-one-color batches)
TOP_COLORS_WARM = [
    "soft CREAM", "pale BUTTER YELLOW", "warm CAMEL", "TERRACOTTA",
    "soft BLUSH PINK", "warm IVORY", "DUSTY ROSE", "SAND",
]
TOP_COLORS_COOL = [
    "SAGE GREEN", "DEEP TEAL", "SLATE BLUE", "EUCALYPTUS",
    "COBALT BLUE", "DUSTY LAVENDER", "FOREST GREEN", "STEEL GREY",
]
TOP_COLORS_ALL = TOP_COLORS_WARM + TOP_COLORS_COOL


def get_top(shot_index: int, color_override: str | None = None) -> str:
    """Return (color + silhouette description) for shot N, guaranteed varied."""
    top_key, top_desc = TOPS_ROTATION[shot_index % len(TOPS_ROTATION)]
    if color_override:
        color = color_override
    else:
        color = TOP_COLORS_ALL[shot_index % len(TOP_COLORS_ALL)]
    return f"{color} {top_desc}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. STUDIO BACKDROP — HARDLOCKED PALETTE
# ─────────────────────────────────────────────────────────────────────────────

# APPROVED — warm neutral tones only. Must cycle; no repeat in same batch.
STUDIO_BACKDROPS = [
    "warm SAND (#C8AA8A) seamless",          # 0
    "MUSHROOM (#B8A898) linen seamless",     # 1
    "soft TERRACOTTA CLAY (#A0614A) seamless",  # 2
    "warm STONE (#9E9488) seamless",         # 3
    "WARM CREAM (#EDE0CC) seamless",         # 4
    "muted SAGE MIST (#8A9A7E) seamless",    # 5
    "dusty MAUVE (#9A7A82) seamless",        # 6
    "warm PARCHMENT (#D9C8A8) seamless",     # 7
    "soft DUNE (#C4A882) seamless",          # 8
    "muted CLAY ROSE (#B88878) seamless",    # 9
]

# PROHIBITED — must appear verbatim in every studio prompt
BACKDROP_PROHIBITED = (
    "BACKDROP RULES — STRICTLY PROHIBITED: "
    "pure white or near-white backgrounds, cold blue-white overexposed lighting, "
    "hospital-style flat-white studio lights, dark or moody backdrops, "
    "grey concrete, black backgrounds. "
    "The backdrop MUST be a warm neutral tone from the approved palette."
)


def get_backdrop(shot_index: int) -> str:
    """Return approved backdrop color for shot N (cycles, never repeats in 10-shot batch)."""
    return STUDIO_BACKDROPS[shot_index % len(STUDIO_BACKDROPS)]


# ─────────────────────────────────────────────────────────────────────────────
# 4. LIGHTING — SIIL STUDIO COLOR (official preset)
# ─────────────────────────────────────────────────────────────────────────────

SIIL_STUDIO_COLOR = (
    "LIGHTING — SIIL STUDIO COLOR: large diffused softbox key light "
    "upper-front-left ~45°, gentle wrap-around fill right (1-stop softer), "
    "warm 4500K color temperature. Skin luminous, warm, glowing. "
    "Fabric shows clean tone with gentle depth — no blown highlights, no cold cast. "
    "Premium fashion-wellness editorial feel."
)

SIIL_STUDIO_COLOR_SHORT = (
    "Soft diffused 4500K studio light, large upper-left softbox key, gentle right fill. "
    "Warm neutral backdrop. Luminous skin. Zero harsh shadows."
)

# Aliases for backward compat
SIIL_WARM_EDITORIAL       = SIIL_STUDIO_COLOR
SIIL_WARM_EDITORIAL_SHORT = SIIL_STUDIO_COLOR_SHORT


# ─────────────────────────────────────────────────────────────────────────────
# 5. OSTOMY SCAR — STANDARD BLOCK
# ─────────────────────────────────────────────────────────────────────────────

OSTOMY_SCAR = (
    "OSTOMY SCAR (include always): "
    "The model has a subtle, fully-healed post-surgical scar on the lower abdomen "
    "around the ostomy stoma area — small, neat, slightly lighter than surrounding skin, "
    "smooth and faded. Visible in the gap between wrap/belt and clothing. "
    "Shown with dignity, photographic realism. Not hidden, not exaggerated."
)


# ─────────────────────────────────────────────────────────────────────────────
# 6. PRODUCT DESCRIPTIONS
# ─────────────────────────────────────────────────────────────────────────────

WRAP_DESC_BASIC = (
    "SIIL BASIC WRAP (shape from Ref 2): smooth wide stretch-fabric band worn "
    "around the lower abdomen/waist, covering the ostomy area. Smooth, matte, "
    "zero creases. Sits from just above hip bones to natural waist. "
    "NOT a belt, NOT a tube top, NOT underwear. Copy silhouette from reference exactly."
)

WRAP_DESC_TUCKED = (
    "SIIL WRAP (TUCKED): wrap is tucked INSIDE high-waist trousers/leggings. "
    "Only the top edge (2-3cm) is visible above the waistband — a confident glimpse. "
    "Rest is hidden inside. This is intentional."
)


# ─────────────────────────────────────────────────────────────────────────────
# 7. MODEL IDENTITIES
# ─────────────────────────────────────────────────────────────────────────────

AMARA_ID = (
    "IDENTITY — Amara: African American fashion model, ~30-35, 5'11\" tall, "
    "slim runway-model build, flawless rich deep ebony/dark-mahogany skin, "
    "luminous radiant glow, refined high cheekbones, sculpted jawline, long slender neck. "
    "Long sleek straight black hair past shoulders. Warm dark-brown almond-shaped eyes. "
    "Soft editorial makeup. KEEP FACE EXACTLY from Ref 1."
)

KIM_ID = (
    "IDENTITY — Kim: East Asian (Korean) fashion model, ~25-30, 5'8\" tall, "
    "slim elegant build, flawless warm light porcelain skin, gentle high cheekbones, "
    "long sleek straight black hair past shoulders. Warm dark-brown almond-shaped eyes. "
    "Soft natural editorial makeup. KEEP FACE EXACTLY from Ref 1."
)

# ─── DEPRECATED MODELS (do not create new campaign batches for these) ─────────
# Gracia: portrait is in model_refs/ for regenning EXISTING gallery images only.
# Do not reference Gracia in new campaign scripts or new batch generation.
_DEPRECATED_CAMPAIGN_MODELS = ["Gracia"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. MASTER PROMPT BUILDERS
# ─────────────────────────────────────────────────────────────────────────────

def build_studio_prompt(
    model_id: str,
    wrap_color_prompt: str,
    shot_index: int,
    top_override: str | None = None,
    pose_desc: str = "standing tall, arms relaxed, confident direct gaze",
    untucked: bool = True,
) -> str:
    """
    Build a complete, rule-compliant studio shot prompt.

    All SIIL hardcoded rules are applied automatically:
      - Backdrop from approved warm-neutral palette (cycled by shot_index)
      - Top from variety rotation (cycled by shot_index)
      - Footwear: BARE FEET enforced
      - Lighting: SIIL Studio Color
      - Ostomy scar included
    """
    top     = top_override or get_top(shot_index)
    backdrop = get_backdrop(shot_index)
    tuck_str = (
        f"Wrap is worn UNTUCKED — fully visible outer layer on waist/abdomen. "
        f"No trousers below. Both long legs visible. {FOOTWEAR_STUDIO}"
        if untucked else WRAP_DESC_TUCKED
    )

    return f"""Premium real fashion editorial STUDIO photograph. ULTRA-WIDE 2:1 hero canvas — wider than tall, cinematic proportion.

BACKDROP: {backdrop} fills the full wide frame. {BACKDROP_PROHIBITED}

{model_id}

OUTFIT:
TOP: {top}. Cropped, ends at natural waist. Bare midriff below.
WRAP: {WRAP_DESC_BASIC}
Wrap color: {wrap_color_prompt}
{tuck_str}

{OSTOMY_SCAR}

COMPOSITION: Wide 2:1 hero format. Model centered or slightly offset. Full body head-to-toe — NEVER crop head or hands. Wide format with breathing room both sides.
POSE: {pose_desc}. Natural relaxed hands, correct finger anatomy.

LIGHTING: {SIIL_STUDIO_COLOR_SHORT}
STYLE: Brand-tier fashion wellness editorial. Wrap clearly featured. Empowering, confident, positive.

{FOOTWEAR_NO_FLIPFLOPS}

Ref 1 = model identity (keep face, skin, hair exactly).
Ref 2 = SIIL Wrap shape reference — copy silhouette exactly, adapt color."""


def build_lifestyle_prompt(
    model_id: str,
    wrap_color_prompt: str,
    scene_name: str,
    scene_desc: str,
    lighting: str,
    footwear_note: str | None = None,
) -> str:
    """
    Build a complete, rule-compliant lifestyle (tucked) shot prompt.

    Footwear defaults to FOOTWEAR_LIFESTYLE_CASUAL unless overridden.
    For running scenes, pass footwear_note=FOOTWEAR_RUNNING.
    """
    fw = footwear_note or FOOTWEAR_LIFESTYLE_CASUAL

    return f"""Real brand-tier fashion editorial photograph. ULTRA-WIDE 2:1 cinematic hero canvas. Professional advertising quality.

{model_id}

SCENE: {scene_name}
{scene_desc}

SIIL WRAP (TUCKED): {wrap_color_prompt} wrap is tucked INSIDE high-waist trousers/leggings. Top edge visible 2-3cm above waistband — confident intentional glimpse. Rest hidden inside. Shown naturally as part of outfit.

{OSTOMY_SCAR}

{fw}
{FOOTWEAR_NO_FLIPFLOPS}

COMPOSITION: Ultra-wide 2:1 cinematic frame. Environment fills frame dramatically. Full body or 3/4 body — NEVER crop head. Model powerfully placed in scene.
LIGHTING: {lighting}. World-class advertising photography.
STYLE: Hasselblad medium-format editorial feel. Real person, NOT illustrated. Brand-tier fashion-wellness advertising. Bold, aspirational, emotionally powerful.

Ref 1 = model identity (keep face, skin, hair exactly).
Ref 2 = SIIL Wrap shape reference — only top edge visible above waistband."""


# ─────────────────────────────────────────────────────────────────────────────
# 9. VALIDATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def validate_model(model_name: str) -> None:
    """Raise ValueError if model is deprecated for new campaign generation."""
    if model_name in _DEPRECATED_CAMPAIGN_MODELS:
        raise ValueError(
            f"Model '{model_name}' is deprecated for new campaign generation. "
            f"Use existing gallery images only. Approved new-campaign models: Amara, Kim (+ others)."
        )
