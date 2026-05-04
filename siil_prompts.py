"""
SIIL GENERATION PROMPT CONSTANTS
==================================
Shared identity blocks, ostomy scar, studio lighting preset, and wrap desc.
Import this in every generation script — these are the single source of truth.

Usage:
    from siil_prompts import SIIL_WARM_EDITORIAL, OSTOMY_SCAR, WRAP_DESC
    from siil_colors import WRAP_BASIC, get_wrap_prompt
"""

# ── STUDIO LIGHTING PRESET — "SIIL WARM EDITORIAL" ────────────────────────────
# Derived from official SIIL product reference photography (Gracia, Sara, Tara
# studio sessions). Characteristics:
#   - Warm neutral seamless backdrop (sand / linen / mushroom — never white)
#   - Large softbox key from upper-front-left, ~45 degrees
#   - Gentle fill from opposite side, ~1 stop below key
#   - Warm color temperature (~4500K), golden skin-luminance
#   - Zero harsh shadows; wrap and skin both read clean and dimensional
#   - Result: upscale fashion-wellness editorial feel

SIIL_WARM_EDITORIAL = """LIGHTING STYLE — SIIL WARM EDITORIAL:
Shoot with a large diffused softbox key light positioned upper-front-left at ~45 degrees, gentle wrap-around fill from the right (1-stop softer than key), warm color temperature (~4500K). Background is a seamless warm neutral backdrop — sand, mushroom, or terracotta linen — lit slightly brighter than model to create separation. Skin should appear luminous, warm, and glowing. Fabric shows clean tone with gentle depth — no blown-out highlights, no cold cast. Overall feel: premium fashion-wellness editorial, like a high-end medical-lifestyle brand shoot."""

# Short version for inline use
SIIL_WARM_EDITORIAL_SHORT = "Soft diffused luxe studio daylight. Warm wrap-around 4500K light, large upper-left softbox key, gentle right fill. Warm neutral backdrop. Luminous glowing skin. Zero harsh shadows. Premium fashion-wellness editorial."

# ── OSTOMY SCAR — STANDARD BLOCK ──────────────────────────────────────────────
# Add this to EVERY generation prompt for models wearing the SIIL wrap/belt.
# Shows the wrap is worn for a real reason — authentic, dignified, empowering.

OSTOMY_SCAR = """OSTOMY SCAR (IMPORTANT — include always):
The model has a subtle, realistic, fully-healed post-surgical scar on the lower abdomen around the ostomy stoma area. This is a small, neat surgical incision scar — slightly lighter in color than the surrounding skin, smooth, faded, clearly healed (not red, not raised, not fresh). The scar is visible in the gap between the top of the wrap/belt and the bottom of the clothing — shown with dignity and naturalness, as part of everyday life. Render with photographic realism: faint but visible, not hidden, not exaggerated."""

# ── WRAP PRODUCT DESCRIPTION (SHAPE) ──────────────────────────────────────────
WRAP_DESC_BASIC = """SIIL BASIC WRAP (shape from Ref 2): A smooth wide stretch-fabric band worn around the lower abdomen and waist — covers the ostomy area with a clean flat surface. Smooth, matte, zero creases. The wrap sits from just above the hip bones up to the natural waist. Copy the silhouette from the reference image exactly — it is NOT a belt, NOT a tube top, NOT underwear. It is a wide band covering the lower abdomen."""

WRAP_DESC_TUCKED = """SIIL WRAP (TUCKED IN): The SIIL wrap is tucked INSIDE the high-waist trousers/leggings. The wrap top edge is visible 2-3cm above the waistband — a subtle intentional glimpse. The rest is hidden inside the waistband. This is the only part that shows — and it is shown confidently."""

# ── MODEL IDENTITY BLOCKS ──────────────────────────────────────────────────────

AMARA_ID = """IDENTITY — Amara: Mixed-race (Black/Latina) woman, ~30-35 years old. 5'7" tall, curvy athletic build, smooth warm medium-brown skin with a natural healthy glow. Beautiful round face with strong cheekbones and a warm confident smile. Long natural curly/wavy dark brown hair, full and voluminous. Dark expressive brown eyes with natural lashes. Natural, minimal editorial makeup. KEEP FACE EXACTLY from Ref 1."""

KIM_ID = """IDENTITY — Kim: East Asian (Korean) fashion model, ~25-30 years old, 5'8" tall, slim elegant build, flawless warm light porcelain skin with natural luminous glow, refined soft features, gentle high cheekbones, elegant jawline, long slender neck. Long sleek straight black hair past shoulders. Warm dark-brown almond-shaped eyes. Soft natural editorial makeup. KEEP FACE EXACTLY from Ref 1."""

# ── COMBINED STUDIO SHOT TEMPLATE ─────────────────────────────────────────────
def studio_prompt(model_id: str, wrap_color_prompt: str, top_desc: str,
                  pose_desc: str, backdrop: str, untucked: bool = True) -> str:
    """Build a complete studio shot prompt with all SIIL standard blocks."""
    tuck_str = (
        f"Wrap is worn UNTUCKED — it is the OUTER LAYER, fully visible on the model's waist/abdomen. "
        f"No trousers. Both legs visible below the wrap. BARE FEET — no shoes, no slippers, no sandals."
        if untucked else
        WRAP_DESC_TUCKED
    )
    return f"""Premium real fashion editorial STUDIO photograph. ULTRA-WIDE 2:1 hero canvas — wider than tall, cinematic proportion.
{backdrop} seamless studio backdrop fills the full wide frame. NOT white.

{model_id}

OUTFIT:
TOP: {top_desc}. Cropped, ends at natural waist. Bare midriff below.
WRAP: {WRAP_DESC_BASIC}
Wrap color: {wrap_color_prompt}
{tuck_str}

{OSTOMY_SCAR}

COMPOSITION: Wide 2:1 hero format. Model centered or slightly offset. Full body visible — head to toe, never cropped. Wide format gives breathing room on both sides.
POSE: {pose_desc}. Natural relaxed hands with correct finger anatomy.

LIGHTING: {SIIL_WARM_EDITORIAL_SHORT}
STYLE: Brand-tier fashion wellness editorial. Wrap clearly featured. Empowering, confident, positive.

Ref 1 = model identity (keep face, skin, hair exactly).
Ref 2 = SIIL Basic Wrap shape — copy silhouette exactly."""


def lifestyle_prompt(model_id: str, wrap_color_prompt: str, scene_name: str,
                     scene_desc: str, lighting: str) -> str:
    """Build a complete lifestyle tucked-wrap prompt with all SIIL standard blocks."""
    return f"""Real brand-tier fashion editorial photograph. ULTRA-WIDE 2:1 cinematic hero canvas. Professional advertising quality.

{model_id}

SCENE: {scene_name}
{scene_desc}

SIIL WRAP (TUCKED):
{WRAP_DESC_TUCKED}
Wrap color: {wrap_color_prompt}

{OSTOMY_SCAR}

COMPOSITION: Ultra-wide 2:1 cinematic frame. Environment fills the frame dramatically. Full body or 3/4 body — never crop head. Model powerfully placed within the scene.
LIGHTING: {lighting}. World-class advertising photography quality.
STYLE: Real person, NOT illustrated. Brand-tier fashion-wellness advertising. Bold, aspirational, emotionally powerful.

Ref 1 = model identity (keep face, skin, hair exactly).
Ref 2 = SIIL Basic Wrap shape — tucked inside waistband, only top edge visible."""


# ── QUICK TEST ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys; sys.stdout.reconfigure(encoding="utf-8")
    from siil_colors import get_wrap_prompt

    print("SIIL PROMPTS — Quick Test")
    print("=" * 60)
    print("\n[OSTOMY_SCAR]")
    print(OSTOMY_SCAR)
    print("\n[SIIL_WARM_EDITORIAL - short]")
    print(SIIL_WARM_EDITORIAL_SHORT)
    print("\n[Studio prompt sample - Amara Black]")
    p = studio_prompt(
        model_id=AMARA_ID,
        wrap_color_prompt=get_wrap_prompt("Black"),
        top_desc="fitted COBALT BLUE ribbed cropped short-sleeve top",
        pose_desc="standing tall, arms relaxed at sides, direct confident gaze",
        backdrop="warm TERRACOTTA CLAY",
    )
    print(p[:300], "...")
