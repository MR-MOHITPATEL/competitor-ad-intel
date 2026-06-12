"""
Discover layout roots — pure structural skeletons shared across competitor ads.

A layout root = the spatial structure/skeleton of the ad ONLY.
Examples: "Two-Column Product-Left", "Centered Product Minimal", "Full-Bleed Lifestyle Overlay".

IMPORTANT: Layout roots ignore CONTENT TYPE and MESSAGING.
Two ads with different messages and different content (stats vs ingredients) belong in the
SAME layout root if their spatial structure (zone positions, proportions) is identical.

Step 6 = Visual format + content type (what fills the zones)
Step 7 = Pure structural skeleton (how the zones are arranged, proportions, grid)

Use layout roots for:
  1. Briefing designers with exact spatial blueprints
  2. Finding structural gaps competitors haven't used

Sends actual ad images + structural signals to Gemini for clustering.
Primary model: Gemini 2.5 Flash (GOOGLE_API_KEY in .env)
Fallback: llama-3.3-70b-versatile via Groq
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("layout_discoverer")

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_FALLBACK_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a senior art director and spatial layout expert. "
    "You will be shown actual ad images. "
    "Cluster them into 5-7 LAYOUT ROOTS based ONLY on their spatial structure — "
    "the grid, zone positions, and proportions of the frame. "
    "IGNORE: what product is shown, what the text says, what condition is targeted, content type. "
    "ONLY look at: how many zones, where each zone sits, what proportion of the frame each zone takes. "
    "Two ads with completely different content (one has stats, one has a person) belong in the SAME root "
    "if their spatial skeleton is identical (e.g. both split the frame 50/50 left-right). "
    "Return ONLY valid JSON, no markdown, no commentary."
)

LAYOUT_SCHEMA = """{
  "layout_roots": [
    {
      "layout_id": "<kebab-case id, e.g. two-col-equal-split>",
      "layout_name": "<structural name describing the skeleton, e.g. Two-Column Equal Split>",
      "layout_emoji": "<emoji>",
      "description": "<2-3 sentences: describe only the spatial structure — zone count, positions, proportions. No mention of content.>",
      "skeleton": "<precise structural description: e.g. 'Frame split vertically 50/50. Left zone: single content block, vertically centred. Right zone: single content block, vertically centred. No header zone. No footer zone.'>",
      "zones": "<comma-separated list of zones with proportions, e.g. 'LEFT-40%, RIGHT-60%' or 'TOP-20%, CENTRE-60%, BOTTOM-20%'>",
      "flexibility": "<what content types this skeleton can hold, e.g. 'works for: stats, product+benefits, before/after, person+text'>",
      "structure_brief": "<Step-by-step spatial blueprint a designer can follow without seeing any reference: (1) Canvas setup (2) Zone 1 position and size (3) Zone 2 position and size (4) Zone 3 if exists (5) Text placement rules (6) Product placement rule>",
      "saturation_signal": "<dominant|common|occasional|rare>",
      "ad_ids": ["<ad_id>"],
      "ad_count": 0
    }
  ],
  "dominant_layout": "<layout_id>",
  "underused_layouts": ["<structural skeleton not present in these ads, e.g. diagonal-split, circular-frame, three-column-grid>"],
  "summary": "<2-3 sentences: dominant structural patterns, what is saturated, structural white space>"
}"""


def _extract_structural_signals(vision_ad: dict) -> dict:
    """Extract only structural/spatial signals — ignore content."""
    fp = vision_ad.get("layout_fingerprint") or {}
    return {
        "layout": (vision_ad.get("layout_template") or "")[:150],
        "zones": fp.get("product_zone", ""),
        "overlay": fp.get("overlay_type", ""),
        "structure": (vision_ad.get("scene_description") or "")[:80],
    }


def _get_primary_image_url(ad_id: str, scored_map: dict, vision_ad: dict | None = None) -> str:
    """Get best available image URL — prefers Supabase URLs."""
    for source in [scored_map.get(ad_id, {}) or {}, vision_ad or {}]:
        urls = (
            source.get("ad_supabase_image_urls")
            or source.get("ad_remote_image_urls")
            or source.get("ad_image_urls")
            or []
        )
        if urls:
            first = urls[0]
            if str(first).startswith("http"):
                return first
        primary = source.get("primary_image_url", "") or ""
        if primary.startswith("http"):
            return primary
    return ""


def build_prompt(
    vision_ads: list[dict],
    scored_map: dict,
    existing_roots: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    sorted_ads = sorted(
        vision_ads,
        key=lambda a: (scored_map.get(a.get("ad_id", ""), {}) or {}).get("composite_score") or 0,
        reverse=True,
    )
    sample = sorted_ads[:30]

    slim_ads = []
    image_items = []

    for i, ad in enumerate(sample):
        ad_id = ad.get("ad_id", "")
        signals = _extract_structural_signals(ad)
        img_url = _get_primary_image_url(ad_id, scored_map, ad)
        idx = i + 1
        slim_ads.append({"idx": idx, "id": ad_id, **signals})
        image_items.append({"idx": idx, "ad_id": ad_id, "url": img_url})

    hint = ""
    if existing_roots:
        hint = "EXISTING LAYOUT ROOTS (reuse when structure matches):\n"
        for r in existing_roots:
            hint += f'  • [{r["layout_id"]}] "{r["layout_name"]}" — {r.get("skeleton","")[:100]}\n'
        hint += "\n"

    prompt = (
        f"You are looking at {len(slim_ads)} ad images (labeled [1] to [{len(slim_ads)}]).\n"
        f"Cluster them into 5-7 LAYOUT ROOTS based ONLY on MACRO spatial structure.\n\n"
        + (hint if hint else "")
        + "CLUSTERING RULES — READ CAREFULLY:\n"
        "- Group by the OVERALL FRAME DIVISION only — how the canvas is split at a macro level\n"
        "- IGNORE ALL OF THESE: product name, text content, colors, brand, audience, badge positions\n"
        "- Think of it like a WIREFRAME sketch — strip everything to grey rectangles and ask: same rectangle arrangement?\n"
        "- If two ads have the same OVERALL frame structure = SAME root, even if:\n"
        "  • One has a person, the other has a product bottle\n"
        "  • One has a discount badge top-right, the other has text top-left (minor variation = same root)\n"
        "  • One shows stats, the other shows ingredients (content type doesn't matter)\n"
        "- Discover the layouts that ACTUALLY EXIST in these ads — do not force into predefined buckets\n"
        "- Create a new root only when the macro frame structure is genuinely different from all others\n"
        "- Minimum 3 ads per root — merge thin groups into the closest structural match\n"
        "- When in doubt, MERGE rather than split\n\n"
        "EXAMPLES of what makes two ads the SAME layout root:\n"
        "  • Person holding product filling the frame + close-up body with patch filling the frame → SAME (both full-bleed)\n"
        "  • Headline at top + product center + benefit icons at bottom bar + Headline at top + image center + CTA bottom → SAME (three-zone stack)\n"
        "  • Product left side + stats right side + Product right side + benefits left side → SAME (left-right split, direction doesn't matter)\n\n"
        "EXAMPLES of what makes two ads DIFFERENT layout roots:\n"
        "  • Full-bleed scene (no clear zones) vs. clean two-column split (clear left/right divide)\n"
        "  • Centered single product on white vs. lifestyle scene filling the frame\n\n"
        f"STRUCTURAL SIGNALS (use alongside the images):\n"
        f"{json.dumps(slim_ads, separators=(',',':'), ensure_ascii=False)}\n\n"
        f"Return ONLY a JSON object matching this schema:\n{LAYOUT_SCHEMA}"
    )

    return prompt, image_items


def _call_gemini_with_images(
    prompt: str,
    image_items: list[dict],
    google_api_key: str,
) -> str:
    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=google_api_key)
    contents = []
    images_sent = 0

    for item in image_items:
        url = item.get("url", "")
        if url and url.startswith("http"):
            ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
            try:
                contents.append(gtypes.Part.from_uri(file_uri=url, mime_type=mime))
                contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']}")
                images_sent += 1
            except Exception as e:
                logger.debug("Skipping image %s: %s", item["ad_id"], e)
                contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']} (unavailable)")
        else:
            contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']} (no URL)")

    contents.append(prompt)
    logger.info("Sending %d images to Gemini for layout clustering.", images_sent)

    models_to_try = [GEMINI_MODEL, "gemini-2.0-flash"]
    for model in models_to_try:
        if model != GEMINI_MODEL:
            logger.warning("Falling back to %s…", model)
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=gtypes.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=16000,
                        thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
                    ),
                )
                return response.text.strip()
            except Exception as e:
                err = str(e)
                if "quota" in err.lower() or "429" in err or "rate" in err.lower():
                    wait = 15 * (2 ** attempt)
                    logger.warning("Gemini rate limit — waiting %ds…", wait)
                    time.sleep(wait)
                elif "503" in err or "unavailable" in err.lower():
                    logger.warning("Gemini 503 on %s — will try next model.", model)
                    break
                elif "payload" in err.lower() or "413" in err:
                    logger.warning("Payload too large — retrying text-only.")
                    return _call_gemini_text_only(prompt, client)
                else:
                    logger.error("Gemini error: %s", e)
                    raise
    raise RuntimeError("Gemini exhausted all models/attempts")


def _call_gemini_text_only(prompt: str, client) -> str:
    from google.genai import types as gtypes
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=8192,
            thinking_config=None,
        ),
    )
    return response.text.strip()


def _call_groq_fallback(prompt: str) -> str:
    client = GroqKeyPool().client
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=GROQ_FALLBACK_MODEL,
                max_tokens=4000,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "429" in err or "rate_limit" in err.lower():
                wait = 20 * (2 ** attempt)
                logger.warning("Groq rate limited — waiting %ds…", wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Groq exhausted after 4 attempts")


def run(
    page_label: str,
    analyzed_dir: str = "data/analyzed",
    scored_dir: str = "data/scored",
    force: bool = False,
) -> Path:
    analyzed_dir = Path(analyzed_dir)
    output_path = analyzed_dir / f"{page_label}_layout_roots.json"
    scored_path = Path(scored_dir) / f"{page_label}_scored.json"

    scored_newer = (
        scored_path.exists()
        and output_path.exists()
        and scored_path.stat().st_mtime > output_path.stat().st_mtime
    )
    if output_path.exists() and not force and not scored_newer:
        logger.info("Cache hit — skipping layout discovery. Use --force to rerun.")
        return output_path

    existing_roots: list[dict] = []
    if output_path.exists():
        try:
            prev = load_json(output_path)
            existing_roots = prev.get("layout_roots", [])
        except Exception:
            pass

    logger.info("Waiting 5s before layout discovery…")
    time.sleep(5)

    vision_path = analyzed_dir / f"{page_label}_vision_analysis.json"
    if not vision_path.exists():
        raise FileNotFoundError(f"Vision analysis not found: {vision_path}. Run Step 4 first.")

    vision_data = load_json(vision_path)
    vision_ads = [a for a in vision_data if not a.get("error") and a.get("visual_format")]

    if not vision_ads:
        save_json({"layout_roots": [], "summary": "No valid vision analyses found."}, output_path)
        return output_path

    scored_data = load_json(scored_path) if scored_path.exists() else {}
    scored_ads = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data
    scored_map = {a.get("ad_id"): a for a in scored_ads if a.get("ad_id")}

    logger.info("Discovering layout roots for %d ads…", len(vision_ads))

    prompt, image_items = build_prompt(vision_ads, scored_map, existing_roots)
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    if google_api_key:
        logger.info("Using %s with images for layout clustering.", GEMINI_MODEL)
        raw = _call_gemini_with_images(prompt, image_items, google_api_key)
    else:
        logger.info("GOOGLE_API_KEY not set — using Groq fallback.")
        raw = _call_groq_fallback(prompt)

    # Strip markdown fences
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break
    start = raw.find("{")
    if start > 0:
        raw = raw[start:]

    try:
        layout_data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s\nRaw:\n%s", e, raw[:500])
        raise

    # Attach Supabase image URLs for dashboard rendering
    ad_image_map = {
        a.get("ad_id"): (
            a.get("ad_supabase_image_urls")
            or a.get("ad_remote_image_urls")
            or a.get("ad_image_urls")
            or ([a["primary_image_url"]] if a.get("primary_image_url") else [])
        )
        for a in scored_ads
    }
    for root in layout_data.get("layout_roots", []):
        images = []
        for aid in root.get("ad_ids", []):
            imgs = ad_image_map.get(aid) or []
            if imgs:
                images.append({"ad_id": aid, "image_url": imgs[0]})
        root["ad_images"] = images

    save_json(layout_data, output_path)
    logger.info(
        "Saved %d layout roots → %s",
        len(layout_data.get("layout_roots", [])), output_path,
    )
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Discover layout structure roots from competitor ads")
    parser.add_argument("--page-label", required=True)
    parser.add_argument("--analyzed-dir", default="data/analyzed")
    parser.add_argument("--scored-dir", default="data/scored")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(args.page_label, args.analyzed_dir, args.scored_dir, args.force)
