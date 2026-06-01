"""
Generate ad copy + Gemini image prompt for your product,
inspired by a competitor winner ad or theme.

The key principle: copy and image prompt must tell the SAME story.
The visual analysis (story arc, emotional trigger, scene) drives both.

Model: llama-3.3-70b-versatile
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger

logger = get_logger("ad_generator")

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a senior Health & Wellness creative director and prompt engineer specializing in "
    "Gemini Imagen 3. Your job is to reverse-engineer a competitor's exact ad layout and rebuild "
    "it for a new product — preserving every spatial zone, color, proportion, and visual element. "
    "You write image prompts that are so precise a designer could produce the exact layout without "
    "seeing the original. The ad copy and image prompt must tell the EXACT same story — headline, "
    "benefit bullets, and image are one unified creative, not separate pieces. "
    "Return ONLY valid JSON — no commentary, no markdown fences, no extra text."
)

OUTPUT_SCHEMA = """{
  "headline": "<compelling ad headline, max 10 words — must match the story in the image_prompt>",
  "body_copy": "<2-4 sentence ad body copy — expands on the story started by the headline and image>",
  "cta": "<call-to-action text, max 5 words>",
  "image_prompt": "<Ultra-specific Gemini Imagen 3 prompt. Follow this exact structure — every section is required:\\nBACKGROUND: [exact background color/texture, e.g. 'solid white #FFFFFF' or 'light grey gradient top-to-bottom']\\nLAYOUT ZONES: [describe the frame divided into exact spatial zones with proportions, e.g. 'TOP 25%: headline text block, full width. LEFT 45%: mechanism/body illustration, vertically centered. RIGHT 45%: product + vessel on platform, vertically centered. OVERLAY LEFT 20-50%: benefit checklist. BOTTOM 8%: fine-print disclaimer bar.']\\nHEADLINE ZONE: [exact text to render, font style, weight, size relative to frame, color — e.g. 'Text: BALANCE YOUR HORMONES FOR / A BETTER YOU. Two-line, ALL CAPS. Bold sans-serif. Line 1 black, Line 2 olive-green #6B7C3D. Fills top 20% width 90% centered.']\\nMECHANISM/ILLUSTRATION ZONE: [exact illustration — e.g. 'Semi-transparent pink anatomical uterus illustration, no text labels, soft glow, left-center zone, 40% frame height' — or 'none']\\nPRODUCT ZONE: [exact product placement — e.g. '1-liter brown glass bottle with white floral label, upright, bottom-anchored on a light grey circular platform. Clear glass of dark brown liquid placed to its left. Right-center zone, 45% frame height.']\\nBENEFIT CHECKLIST ZONE: [exact text lines, icon style, colors, position — e.g. '4 lines with green filled checkbox icons (#4CAF50): Line1: Healthy Regular Monthly Cycles / Line2: Relief from Hormonal Acne / Line3: Weight Management / Line4: Other Hormonal Symptoms. Left-center overlay, 14px equivalent, dark grey text.']\\nCOLOR PALETTE: [list every color with hex or precise description: background, headline colors, accent colors, icon colors, product colors]\\nPHOTOGRAPHY STYLE: [clean product shot or lifestyle or illustration-heavy; lighting; no shadows or soft shadow; photorealistic or graphic design flat]\\nDO NOT include: [list things to avoid — e.g. 'no people, no outdoor scenes, no gradients on text']>",
  "benefit_bullets": ["<benefit 1>", "<benefit 2>", "<benefit 3>", "<benefit 4>"],
  "creative_rationale": "<1-2 sentences: why this layout template works for this audience>"
}"""


def _build_prompt_from_ad(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    competitor_ad: dict,
    visual_analysis: dict | None,
    key_ingredient: str | None = None,
    ingredient_benefit: str | None = None,
) -> str:
    ad_id = competitor_ad.get("ad_id", "unknown")
    hook = competitor_ad.get("hook_type", "")
    tone = competitor_ad.get("emotional_tone", "")
    claim = competitor_ad.get("core_claim", "")
    cta_style = competitor_ad.get("cta_style", "")
    headline = competitor_ad.get("ad_creative_link_title", "")
    body = (competitor_ad.get("ad_creative_body") or "")[:300]
    days = competitor_ad.get("run_duration_days", "unknown")

    # Build rich visual context block
    visual_block = ""
    if visual_analysis and not visual_analysis.get("error"):
        visual_block = (
            f"\nCOMPETITOR VISUAL TEMPLATE (reverse-engineered from their winning image):\n"
            f"  Format: {visual_analysis.get('visual_format', '')}\n"
            f"  Layout Template: {visual_analysis.get('layout_template', '')}\n"
            f"  Scene: {visual_analysis.get('scene_description', '')}\n"
            f"  Mechanism Element: {visual_analysis.get('mechanism_element', 'none')}\n"
            f"  Product Element: {visual_analysis.get('product_element', '')}\n"
            f"  Benefit Presentation: {visual_analysis.get('benefit_presentation', '')}\n"
            f"  Headline Style: {visual_analysis.get('headline_style', '')}\n"
            f"  Story Arc: {visual_analysis.get('story_arc', '')}\n"
            f"  Emotional Trigger: {visual_analysis.get('emotional_trigger', '')}\n"
            f"  Color Palette: {visual_analysis.get('color_palette', '')}\n"
            f"  REPLICATION GUIDE: {visual_analysis.get('replication_guide', '')}\n"
        )
    else:
        visual_block = (
            f"\nNOTE: No visual analysis available. Use a clean product-infographic layout: "
            f"bold headline top, product hero right, benefit checklist left, white background.\n"
        )

    ingredient_block = ""
    if key_ingredient:
        ingredient_block = (
            f"  Key Ingredient: {key_ingredient}\n"
            f"  Ingredient Properties: {ingredient_benefit or 'natural herb with therapeutic properties'}\n"
            f"  INGREDIENT VISUAL NOTE: The raw {key_ingredient} (actual root/bark/herb pieces, "
            f"photorealistic) MUST appear in the image — place it naturally near or in front of "
            f"the product bottle. Add a small callout label: '{key_ingredient} — "
            f"{ingredient_benefit or 'natural & pure'}'. This communicates SOURCE TRANSPARENCY "
            f"— the viewer sees exactly what's inside the bottle.\n"
        )

    return (
        f"MY PRODUCT:\n"
        f"  Name: {product_name}\n"
        f"  Key Benefit: {key_benefit}\n"
        f"  Target Audience: {target_audience}\n"
        f"{ingredient_block}\n"
        f"COMPETITOR WINNING AD — ran {days} days (ad_id: {ad_id}):\n"
        f"  Hook Type: {hook} | Emotional Tone: {tone} | CTA Style: {cta_style}\n"
        f"  Competitor Headline: {headline}\n"
        f"  Competitor Body (excerpt): {body}\n"
        f"{visual_block}\n"
        f"YOUR TASK:\n"
        f"1. Write ad COPY for my product using the same hook ({hook}) and tone ({tone}).\n"
        f"2. Write 4 benefit bullets (short, punchy — like the competitor's checklist).\n"
        f"3. Write an IMAGE PROMPT that EXACTLY replicates the competitor's visual layout for MY product.\n"
        f"   CRITICAL RULES for the image prompt:\n"
        f"   - Copy the LAYOUT TEMPLATE verbatim from above, zone by zone (TOP/LEFT/RIGHT/CENTER/BOTTOM proportions must match exactly)\n"
        f"   - Copy the COLOR PALETTE from above — use the same background color, text colors, icon colors\n"
        f"   - If the competitor had a mechanism/body illustration (mechanism_element from above), keep that illustration in the same zone but adapt it to my product's benefit ({key_benefit})\n"
        f"   - Replace the competitor's product with MY product: {product_name}\n"
        f"   - Replace competitor's benefit text with my benefit bullets (which you write in step 2)\n"
        f"   - Replace competitor's headline with MY headline (which you write in step 1)\n"
        f"   - Keep all OTHER visual elements (platform, vessel/glass, icons, fine print bar) identical to competitor\n"
        f"   - The prompt MUST include: BACKGROUND, LAYOUT ZONES, HEADLINE ZONE, MECHANISM/ILLUSTRATION ZONE, PRODUCT ZONE, BENEFIT CHECKLIST ZONE, COLOR PALETTE, PHOTOGRAPHY STYLE, DO NOT include\n"
        f"   - Every zone must have exact proportions (e.g. 'left 45% of frame'), exact colors, exact text content\n"
        + (
            f"   - INGREDIENT ELEMENT (MANDATORY): In the PRODUCT ZONE, place photorealistic raw "
            f"{key_ingredient} pieces (actual herb/root/bark, not illustration) in front of or beside "
            f"the product bottle on the platform. Add a small floating callout label pointing to the "
            f"ingredient: '{key_ingredient} — {ingredient_benefit or 'natural & pure'}'. "
            f"This shows the SOURCE of the product — critical for trust.\n"
            if key_ingredient else ""
        )
        + f"\n"
        f"Return ONLY a JSON object matching this schema:\n{OUTPUT_SCHEMA}"
    )


def _build_prompt_from_theme(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    theme: dict,
    key_ingredient: str | None = None,
    ingredient_benefit: str | None = None,
) -> str:
    theme_name = theme.get("theme_name", "")
    description = theme.get("description", "")
    freq = theme.get("frequency", "")
    dominant_angle = theme.get("dominant_emotional_angle", "")
    most_used_hook = theme.get("most_used_hook", "")

    ingredient_block = ""
    if key_ingredient:
        ingredient_block = (
            f"  Key Ingredient: {key_ingredient}\n"
            f"  Ingredient Properties: {ingredient_benefit or 'natural herb with therapeutic properties'}\n"
            f"  INGREDIENT VISUAL NOTE: Raw {key_ingredient} (actual root/bark/herb pieces, "
            f"photorealistic) must appear beside the product bottle with a callout label: "
            f"'{key_ingredient} — {ingredient_benefit or 'natural & pure'}'.\n"
        )

    return (
        f"MY PRODUCT:\n"
        f"  Name: {product_name}\n"
        f"  Key Benefit: {key_benefit}\n"
        f"  Target Audience: {target_audience}\n"
        f"{ingredient_block}\n"
        f"COMPETITOR THEME TO MIRROR (used in {freq} proven ads):\n"
        f"  Theme Name: {theme_name}\n"
        f"  Description: {description}\n"
        f"  Dominant Emotional Angle: {dominant_angle}\n"
        f"  Most Used Hook: {most_used_hook}\n\n"
        f"YOUR TASK:\n"
        f"1. Write ad COPY for my product that fits this theme — hook type: {most_used_hook}, "
        f"emotional angle: {dominant_angle}.\n"
        f"2. Write an IMAGE PROMPT where:\n"
        f"   - The image visually embodies the theme '{theme_name}'\n"
        f"   - Shows my product ({product_name}) as the solution\n"
        f"   - The emotional tone is {dominant_angle}\n"
        f"   - The image and headline tell the EXACT SAME story — "
        f"a viewer should understand the ad from the image alone\n"
        f"   - Use the mandatory image_prompt structure from the schema: BACKGROUND, LAYOUT ZONES, "
        f"HEADLINE ZONE, MECHANISM/ILLUSTRATION ZONE, PRODUCT ZONE, BENEFIT CHECKLIST ZONE, "
        f"COLOR PALETTE, PHOTOGRAPHY STYLE, DO NOT include\n"
        f"   - Be specific: exact zone proportions, hex colors, exact text overlays, "
        f"exact element placement\n"
        + (
            f"   - INGREDIENT ELEMENT (MANDATORY): In the PRODUCT ZONE, show photorealistic raw "
            f"{key_ingredient} pieces (actual herb/root/bark) beside the product bottle. "
            f"Add a floating callout label: '{key_ingredient} — "
            f"{ingredient_benefit or 'natural & pure'}'. Shows source transparency.\n"
            if key_ingredient else ""
        )
        + f"\nReturn ONLY a JSON object matching this schema:\n{OUTPUT_SCHEMA}"
    )


def _build_prompt_from_root(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    root: dict,
    key_ingredient: str | None = None,
    ingredient_benefit: str | None = None,
) -> str:
    ingredient_block = ""
    if key_ingredient:
        ingredient_block = (
            f"  Key Ingredient: {key_ingredient}\n"
            f"  Ingredient Properties: {ingredient_benefit or 'natural herb with therapeutic properties'}\n"
            f"  INGREDIENT VISUAL NOTE: Raw {key_ingredient} (actual root/bark/herb pieces, "
            f"photorealistic) must appear beside the product bottle with a callout label: "
            f"'{key_ingredient} — {ingredient_benefit or 'natural & pure'}'.\n"
        )

    vt = root.get("visual_template", {})
    mp = root.get("messaging_pattern", {})
    rep = root.get("replication_guide", "")
    ad_count = root.get("ad_count") or len(root.get("ad_ids", []))

    return (
        f"MY PRODUCT:\n"
        f"  Name: {product_name}\n"
        f"  Key Benefit: {key_benefit}\n"
        f"  Target Audience: {target_audience}\n"
        f"{ingredient_block}\n"
        f"COMPETITOR CREATIVE ROOT — '{root.get('root_name','')}' (used across {ad_count} proven ads):\n"
        f"  Description: {root.get('description','')}\n"
        f"  Visual Format: {vt.get('visual_format','')}\n"
        f"  Layout Template: {vt.get('layout','')}\n"
        f"  Key Visual Elements: {', '.join(vt.get('key_visual_elements', []))}\n"
        f"  Color Mood: {vt.get('color_mood','')}\n"
        f"  Mechanism Illustration: {vt.get('mechanism_illustration','none')}\n"
        f"  Hook Type: {mp.get('hook_type','')}\n"
        f"  Emotional Tone: {mp.get('emotional_tone','')}\n"
        f"  Claim Style: {mp.get('claim_style','')}\n"
        f"  Typical Headline Pattern: {mp.get('typical_headline_structure','')}\n"
        f"  CTA Style: {mp.get('cta_style','')}\n"
        f"  REPLICATION GUIDE: {rep}\n\n"
        f"YOUR TASK:\n"
        f"1. Write ad COPY for my product using hook type '{mp.get('hook_type','')}' "
        f"and emotional tone '{mp.get('emotional_tone','')}'.\n"
        f"2. Write 4 benefit bullets following the root's claim style: {mp.get('claim_style','')}.\n"
        f"3. Write an IMAGE PROMPT that synthesizes the BEST elements of this root's visual template "
        f"for MY product. This root was used in {ad_count} ads — your prompt must capture the "
        f"ESSENCE of the template (the spatial layout, color mood, visual elements) as seen across "
        f"all those ads.\n"
        f"   CRITICAL RULES:\n"
        f"   - Follow the replication guide exactly: {rep}\n"
        f"   - Use the layout zones from this root: {vt.get('layout','')}\n"
        f"   - Keep color mood: {vt.get('color_mood','')}\n"
        f"   - Include mechanism illustration if root uses one: {vt.get('mechanism_illustration','none')}\n"
        f"   - Replace any competitor product with MY product: {product_name}\n"
        f"   - Include my headline and benefit bullets as text overlays\n"
        f"   - The prompt MUST have: BACKGROUND, LAYOUT ZONES, HEADLINE ZONE, "
        f"MECHANISM/ILLUSTRATION ZONE, PRODUCT ZONE, BENEFIT CHECKLIST ZONE, "
        f"COLOR PALETTE, PHOTOGRAPHY STYLE, DO NOT include\n"
        + (
            f"   - INGREDIENT ELEMENT (MANDATORY): In the PRODUCT ZONE, show photorealistic raw "
            f"{key_ingredient} pieces beside the product bottle. "
            f"Add callout label: '{key_ingredient} — {ingredient_benefit or 'natural & pure'}'.\n"
            if key_ingredient else ""
        )
        + f"\nReturn ONLY a JSON object matching this schema:\n{OUTPUT_SCHEMA}"
    )


def generate(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    competitor_ad: dict | None = None,
    theme: dict | None = None,
    root: dict | None = None,
    visual_analysis: dict | None = None,
    key_ingredient: str | None = None,
    ingredient_benefit: str | None = None,
) -> dict:
    if not competitor_ad and not theme and not root:
        raise ValueError("Provide competitor_ad, theme, or root as inspiration.")

    if competitor_ad:
        prompt = _build_prompt_from_ad(
            product_name, key_benefit, target_audience,
            competitor_ad, visual_analysis,
            key_ingredient, ingredient_benefit,
        )
    elif root:
        prompt = _build_prompt_from_root(
            product_name, key_benefit, target_audience, root,
            key_ingredient, ingredient_benefit,
        )
    else:
        prompt = _build_prompt_from_theme(
            product_name, key_benefit, target_audience, theme,
            key_ingredient, ingredient_benefit,
        )

    client = GroqKeyPool().client
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1200,
        temperature=0.7,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)
