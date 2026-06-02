"""
Generate ad copy + image prompt for your product,
inspired by a competitor winner ad, theme, strategy root, or visual root.

The key principle: copy and image prompt must tell the SAME story.
Visual root drives the layout; strategy drives the messaging.

Primary model: Gemini 2.5 Flash (GOOGLE_API_KEY in .env)
Fallback model: llama-3.3-70b-versatile via Groq
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger

logger = get_logger("ad_generator")

GEMINI_MODEL         = "gemini-2.5-flash"
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash"
GROQ_MODEL           = "llama-3.3-70b-versatile"

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
  "image_prompt": "<Ultra-specific Gemini Imagen 3 prompt. ALWAYS start with: 'Square 1:1 ratio image. Use the exact product image provided by the user.' Then follow this structure — every section required:\\nBACKGROUND: [exact background color/texture]\\nLAYOUT ZONES: [frame divided into exact spatial zones with proportions — TOP/LEFT/RIGHT/CENTER/BOTTOM %]\\nHEADLINE ZONE: [exact text, font style, weight, size, color, position]\\nMECHANISM/ILLUSTRATION ZONE: [exact illustration description — or 'none']\\nPRODUCT ZONE: [USE THE USER-PROVIDED PRODUCT IMAGE HERE — exact placement, size, platform, props]\\nBENEFIT CHECKLIST ZONE: [exact text lines, icon style, colors, position]\\nCOLOR PALETTE: [every color with hex codes]\\nPHOTOGRAPHY STYLE: [lighting, render style, mood]\\nDO NOT include: [elements to avoid]>",
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
        f"MANDATORY IMAGE PROMPT RULES (apply to every generated image_prompt):\n"
        f"  1. Always begin image_prompt with: 'Square 1:1 ratio image. Use the exact product image provided by the user.'\n"
        f"  2. In PRODUCT ZONE always write: 'USE USER-PROVIDED PRODUCT IMAGE — place it [exact position/size]'\n"
        f"  3. Never generate or describe a hypothetical product — the actual product image will be inserted\n\n"
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


def _build_prompt_from_visual_root(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    visual_root: dict,
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

    ad_count = visual_root.get("ad_count") or len(visual_root.get("ad_ids", []))
    designer_brief = visual_root.get("designer_brief", "")
    saturation = visual_root.get("saturation_signal", "common")

    return (
        f"MY PRODUCT:\n"
        f"  Name: {product_name}\n"
        f"  Key Benefit: {key_benefit}\n"
        f"  Target Audience: {target_audience}\n"
        f"{ingredient_block}\n"
        f"VISUAL FORMAT TO USE — '{visual_root.get('root_name','')}' "
        f"(seen in {ad_count} competitor ads, saturation: {saturation}):\n"
        f"  Description: {visual_root.get('description','')}\n"
        f"  Layout Structure: {visual_root.get('layout_structure','')}\n"
        f"  Content Type: {visual_root.get('content_type','')}\n"
        f"  Color Mood: {visual_root.get('color_mood','')}\n"
        f"  Designer Brief: {designer_brief}\n\n"
        f"YOUR TASK:\n"
        f"1. Write COMPELLING ad COPY for my product ({product_name}):\n"
        f"   - Headline: bold, benefit-driven, max 10 words\n"
        f"   - Body: 2-3 sentences building on the headline, specific to {key_benefit}\n"
        f"   - CTA: action-oriented, max 5 words\n"
        f"   - 4 benefit bullets: short, punchy, specific\n\n"
        f"2. Write a DETAILED IMAGE PROMPT for Midjourney / DALL-E / Canva AI that:\n"
        f"   - EXACTLY follows the '{visual_root.get('root_name','')}' visual format\n"
        f"   - Uses the designer brief as your blueprint: {designer_brief}\n"
        f"   - Layout structure: {visual_root.get('layout_structure','')}\n"
        f"   - Color mood: {visual_root.get('color_mood','')}\n"
        f"   - Replaces competitor content with MY product ({product_name}) and MY benefit ({key_benefit})\n"
        f"   - The prompt must be detailed enough for a designer to produce without seeing any reference\n"
        f"   REQUIRED sections in image_prompt:\n"
        f"   BACKGROUND: exact color/texture\n"
        f"   LAYOUT ZONES: frame divided into exact spatial zones with proportions (TOP/LEFT/RIGHT/CENTER/BOTTOM %)\n"
        f"   HEADLINE ZONE: exact text, font style, size, color, position\n"
        f"   MECHANISM/ILLUSTRATION ZONE: exact illustration or 'none'\n"
        f"   PRODUCT ZONE: exact product placement, size, platform, props\n"
        f"   BENEFIT CHECKLIST ZONE: exact text lines, icon style, colors, position\n"
        f"   COLOR PALETTE: every color with hex codes\n"
        f"   PHOTOGRAPHY STYLE: lighting, render style, mood\n"
        f"   DO NOT INCLUDE: list elements to avoid\n"
        + (
            f"   INGREDIENT ELEMENT (MANDATORY): photorealistic raw {key_ingredient} pieces "
            f"beside the product bottle. Callout label: '{key_ingredient} — "
            f"{ingredient_benefit or 'natural & pure'}'.\n"
            if key_ingredient else ""
        )
        + f"\nReturn ONLY a JSON object matching this schema:\n{OUTPUT_SCHEMA}"
    )


def _call_llm(prompt: str) -> str:
    """Call Gemini 2.5 Flash — required for high-quality ad generation."""
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    if not google_api_key:
        raise EnvironmentError(
            "GOOGLE_API_KEY is not set. Add it to your Streamlit secrets or .env file to use Generate Ad."
        )

    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=google_api_key)

    for model in [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=gtypes.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.7,
                        max_output_tokens=8192,
                        thinking_config=None,
                    ),
                )
                logger.info("Ad generated using %s.", model)
                return response.text.strip()
            except Exception as e:
                err = str(e)
                if "503" in err or "unavailable" in err.lower() or "overloaded" in err.lower():
                    logger.warning("%s unavailable — trying fallback model.", model)
                    break  # try next model
                elif "quota" in err.lower() or "429" in err or "rate" in err.lower():
                    import time
                    wait = 10 * (2 ** attempt)
                    logger.warning("Gemini rate limit — waiting %ds…", wait)
                    time.sleep(wait)
                else:
                    raise

    raise RuntimeError("All Gemini models unavailable. Please try again in a few minutes.")


def generate(
    product_name: str,
    key_benefit: str,
    target_audience: str,
    competitor_ad: dict | None = None,
    theme: dict | None = None,
    root: dict | None = None,
    visual_root: dict | None = None,
    visual_analysis: dict | None = None,
    key_ingredient: str | None = None,
    ingredient_benefit: str | None = None,
) -> dict:
    if not competitor_ad and not theme and not root and not visual_root:
        raise ValueError("Provide competitor_ad, theme, root, or visual_root as inspiration.")

    if competitor_ad:
        prompt = _build_prompt_from_ad(
            product_name, key_benefit, target_audience,
            competitor_ad, visual_analysis,
            key_ingredient, ingredient_benefit,
        )
    elif visual_root:
        prompt = _build_prompt_from_visual_root(
            product_name, key_benefit, target_audience, visual_root,
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

    raw = _call_llm(prompt)

    # Strip markdown fences
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    # Extract outermost JSON object
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > 0:
        raw = raw[start:end]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Response was truncated — retry once with a simpler prompt asking for shorter output
        logger.warning("JSON truncated — retrying with shorter image prompt instruction.")
        short_prompt = prompt + (
            "\n\nIMPORTANT: Keep image_prompt under 400 words. Be concise but precise."
        )
        raw2 = _call_llm(short_prompt)
        if "```" in raw2:
            for part in raw2.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw2 = part
                    break
        s2 = raw2.find("{")
        e2 = raw2.rfind("}") + 1
        if s2 != -1 and e2 > 0:
            raw2 = raw2[s2:e2]
        return json.loads(raw2)
