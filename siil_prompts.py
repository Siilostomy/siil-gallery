"""
SIIL GENERATION PROMPT CONSTANTS
==================================
Shared identity blocks, ostomy scar, ostomy bag, studio lighting preset, and wrap desc.
Import this in every generation script — these are the single source of truth.

Usage:
    from siil_prompts import SIIL_STUDIO_COLOR, OSTOMY_SCAR, OSTOMY_BAG_RIGHT, WRAP_DESC
    from siil_colors import WRAP_BASIC, get_wrap_prompt
"""

# ── STUDIO LIGHTING PRESET — "SIIL STUDIO COLOR" ─────────────────────────────
# Official name: SIIL Studio Color
# Derived from official SIIL product reference photography (Gracia, Sara, Tara
# studio sessions). Characteristics:
#   - Warm neutral seamless backdrop (sand / linen / mushroom — never white)
#   - Large softbox key from upper-front-left, ~45 degrees
#   - Gentle fill from opposite side, ~1 stop below key
#   - Warm color temperature (~4500K), golden skin-luminance
#   - Zero harsh shadows; wrap and skin both read clean and dimensional
#   - Result: upscale fashion-wellness editorial feel

SIIL_STUDIO_COLOR = """LIGHTING STYLE — SIIL STUDIO COLOR:
Shoot with a large diffused softbox key light positioned upper-front-left at ~45 degrees, gentle wrap-around fill from the right (1-stop softer than key), warm color temperature (~4500K). Background is a seamless warm neutral backdrop — sand, mushroom, or terracotta linen — lit slightly brighter than model to create separation. Skin should appear luminous, warm, and glowing. Fabric shows clean tone with gentle depth — no blown-out highlights, no cold cast. Overall feel: premium fashion-wellness editorial, like a high-end medical-lifestyle brand shoot."""

# Short version for inline use
SIIL_STUDIO_COLOR_SHORT = "Soft diffused luxe studio daylight. Warm wrap-around 4500K light, large upper-left softbox key, gentle right fill. Warm neutral backdrop. Luminous glowing skin. Zero harsh shadows. Premium fashion-wellness editorial."

# Aliases for backward compatibility
SIIL_WARM_EDITORIAL = SIIL_STUDIO_COLOR
SIIL_WARM_EDITORIAL_SHORT = SIIL_STUDIO_COLOR_SHORT

# ── OSTOMY SCAR — MODEL-SPECIFIC PINNED COORDINATES ──────────────────────────
# Location is FIXED per model — same spot every image, no drift.
# Anatomy: ileostomy stoma is standard RIGHT lower quadrant.
#   Coordinates from navel: ~3 cm RIGHT, ~4 cm DOWN.
#   Visible in the skin strip between clothing hem and wrap top edge.

# KIM — healed stoma closure scar; warm porcelain skin; horizontal surgical line
# with visible suture track marks (realistic, dignified, not fresh/angry).
OSTOMY_SCAR_KIM = """OSTOMY SCAR — KIM (FIXED LOCATION, REALISTIC HEALED STOMA SCAR):
LOCATION: Lower RIGHT abdomen. Exactly 3 cm to the RIGHT of the navel and 4 cm BELOW it. This position must be identical in every image — do not move it.
APPEARANCE: A fully-healed stoma closure scar — realistic and honest, shown with dignity.
SHAPE: Elongated horizontal surgical scar line, approximately 4-5 cm wide x 1-1.5 cm tall at centre. Like a horizontal ellipse or closed eye shape — NOT a round patch, NOT an oval blob. A real surgical closure line.
TEXTURE: Slightly raised, linear scar tissue. Visible perpendicular suture track marks on both sides of the main scar line — small symmetrical dots or short lines running above and below the main scar (these are permanent stitch track marks from the surgical closure).
COLOR: On Kim's warm light porcelain skin, the healed scar appears as a soft silvery-pink or pale rose-white horizontal line, slightly lighter/pinker than the surrounding skin. The suture track marks are subtle darker-pink dots on either side.
TONE: Real, human, honest — not airbrushed away. Shown as a normal part of her body with complete matter-of-fact dignity. Not dramatic or clinical — just there.
VISIBILITY: Only visible in the skin gap between the bottom hem of her top and the top edge of the SIIL wrap. If that skin gap is not visible, the scar is hidden — that is fine."""

# AMARA — same anatomical location; on her warm medium-brown skin, the healed
# scar has a warm pinkish-brown tone; same horizontal shape with suture tracks.
OSTOMY_SCAR_AMARA = """OSTOMY SCAR — AMARA (FIXED LOCATION, REALISTIC HEALED STOMA SCAR):
LOCATION: Lower RIGHT abdomen. Exactly 3 cm to the RIGHT of the navel and 4 cm BELOW it. This position is fixed — the same in every image, no variation.
APPEARANCE: A fully-healed stoma closure scar — realistic and honest, shown with pride and dignity.
SHAPE: Elongated horizontal surgical scar line, approximately 4-5 cm wide x 1-1.5 cm tall at centre. A real horizontal surgical closure line — NOT a round patch, NOT a smooth oval. The ends taper to points, giving it an eye/ellipse shape.
TEXTURE: Slightly raised, linear scar tissue. Visible perpendicular suture track marks on both sides of the main scar line — small symmetrical dots or short perpendicular lines above and below the scar (permanent surgical stitch track marks).
COLOR: On Amara's warm medium-brown skin, the healed scar appears as a warm pinkish-rose or slightly lighter warm-tan horizontal line — the scar tissue is a touch lighter and pinker than her surrounding skin. The suture track marks appear as small warm-brown dots flanking the scar on both sides.
TONE: Real, human, honest — not hidden or airbrushed. A visible, normal part of her body shown with complete body-positive confidence.
VISIBILITY: Only visible in the skin gap between her clothing hem and the SIIL wrap top edge. If the midriff is covered, the scar is hidden — that is acceptable.

COORDINATE REFERENCE FOR CONSISTENCY: If the navel is at position (0, 0), the scar centre is at (+3 cm RIGHT, +4 cm DOWN) — lower-right quadrant, never on the left side."""

# Legacy alias — updated to match realistic appearance
OSTOMY_SCAR = """OSTOMY SCAR (FIXED LOCATION — lower RIGHT abdomen, 3 cm right of navel, 4 cm below):
Fully-healed stoma closure scar. SHAPE: elongated horizontal surgical scar line ~4-5 cm wide x 1-1.5 cm tall, like a horizontal ellipse. Slightly raised linear scar tissue with visible perpendicular suture track marks (small dots/lines) on both sides of the main scar line. Color slightly lighter/pinker than surrounding skin. Real, honest, dignified — not airbrushed. Only visible in the skin gap between clothing hem and wrap top edge."""

# ── OSTOMY BAG / POUCH DESCRIPTION ────────────────────────────────────────────
# Based on real ostomy product reference photography.
# Key visual facts (critical for AI accuracy):
#   - Shape is ROUND / CIRCULAR / DOME-SHAPED — like a half-sphere or circular disk
#   - It PROTRUDES from the abdomen (convex) — NOT flat against skin
#   - Size: approximately 14-18cm diameter circle
#   - Color: light beige / flesh-tone / warm cream — matte surface
#   - Has a flat adhesive backing plate against skin; dome protrudes forward
#   - The reveal gesture: one hand pulls garment DOWN or to the SIDE to expose it
#   - Model's expression: confident, upward gaze or mirror gaze — empowered, NOT ashamed

OSTOMY_BAG_RIGHT = """OSTOMY POUCH — RIGHT SIDE (KEY VISUAL ELEMENT, must be clearly rendered):
LOCATION: Lower RIGHT abdomen. The pouch attaches at the stoma site — 3 cm to the RIGHT of the navel, 4 cm BELOW it. Always right lower quadrant, never left.
SHAPE: ROUND and DOME-SHAPED — a circular convex pouch like a half-sphere or flattened dome. Approximately 14-18 cm in diameter. The pouch protrudes from the abdomen — it is NOT flat. It is visible, prominent, and clearly dome-shaped.
COLOR: Light beige / warm cream / flesh-tone. Matte surface. The backing plate is flat against skin; the dome protrudes forward.
VISIBILITY: The pouch must be CLEARLY VISIBLE and PROMINENT — the central visual element of the reveal moment. Do NOT minimise or flatten it. It is a real ostomy bag worn with full confidence.
REVEAL GESTURE: The model intentionally pulls her garment (wrap/top) DOWN or to the SIDE with one hand to reveal the pouch. Her expression is confident, proud, and empowered — not apologetic. She may look at the mirror, look upward, or straight at camera with a natural warm smile."""

OSTOMY_BAG_REVEAL_AMARA = """OSTOMY POUCH REVEAL — AMARA:
Amara deliberately reveals her ostomy pouch by lifting or pulling aside the SIIL wrap with one hand. The pouch is on her lower RIGHT abdomen — round, dome-shaped, light beige, clearly protruding. She shows it with complete ownership and pride. Her other hand is relaxed — on her hip, touching her side, or at her chest. Her expression is powerful and beautiful: chin up, warm smile, direct gaze. The pouch is the hero of this moment alongside her confidence."""

# ── WRAP PRODUCT DESCRIPTION (SHAPE) ──────────────────────────────────────────
WRAP_DESC_BASIC = """SIIL BASIC WRAP (shape from Ref 2): A smooth wide stretch-fabric band worn around the lower abdomen and waist — covers the ostomy area with a clean flat surface. Smooth, matte, zero creases. The wrap sits from just above the hip bones up to the natural waist. Copy the silhouette from the reference image exactly — it is NOT a belt, NOT a tube top, NOT underwear. It is a wide band covering the lower abdomen."""

WRAP_DESC_TUCKED = """SIIL WRAP (TUCKED IN): The SIIL wrap is tucked INSIDE the high-waist trousers/leggings. The wrap top edge is visible 2-3cm above the waistband — a subtle intentional glimpse. The rest is hidden inside the waistband. This is the only part that shows — and it is shown confidently."""

# ── MODEL IDENTITY BLOCKS ──────────────────────────────────────────────────────

AMARA_ID = """IDENTITY — Amara: Mixed-race (Black/Latina) woman, ~30-35 years old. 5'7" tall, curvy athletic build, smooth warm medium-brown skin with a natural healthy glow. Beautiful round face with strong cheekbones and a warm confident smile. Long natural curly/wavy dark brown hair, full and voluminous. Dark expressive brown eyes with natural lashes. Natural, minimal editorial makeup.
PERMANENT PHYSICAL TRAIT — OSTOMY SCAR: Amara has a healed stoma closure scar on her lower RIGHT abdomen — 3 cm right of the navel, 4 cm below it. It is an elongated horizontal surgical scar line, ~4-5 cm wide, slightly raised, warm pinkish-rose tone against her medium-brown skin, with visible perpendicular suture track marks on both sides. This scar is a permanent, consistent part of her body in every image — visible whenever her midriff is exposed, shown naturally and with complete confidence.
KEEP FACE EXACTLY from Ref 1."""

KIM_ID = """IDENTITY — Kim: East Asian (Korean) fashion model, ~25-30 years old, 5'8" tall, slim elegant build, flawless warm light porcelain skin with natural luminous glow, refined soft features, gentle high cheekbones, elegant jawline, long slender neck. Long sleek straight black hair past shoulders. Warm dark-brown almond-shaped eyes. Soft natural editorial makeup.
PERMANENT PHYSICAL TRAIT — OSTOMY SCAR: Kim has a healed stoma closure scar on her lower RIGHT abdomen — 3 cm right of the navel, 4 cm below it. It is an elongated horizontal surgical scar line, ~4-5 cm wide, slightly raised, silvery-pink tone against her porcelain skin, with visible perpendicular suture track marks on both sides. This scar is a permanent, consistent part of her body in every image — visible whenever her midriff is exposed, shown naturally with complete dignity.
KEEP FACE EXACTLY from Ref 1."""

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
