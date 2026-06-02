"""
Discover visual roots — format + content-type archetypes shared across competitor ads.

A visual root = a reusable VISUAL TEMPLATE: same ad layout structure + same type of content shown.
Examples: "Product with Stat Callout Cards", "Lifestyle Person Overlay", "Food/Drink Closeup".

IMPORTANT: Visual roots are defined by HOW THE AD LOOKS, not how it persuades.
Group by visual layout only — two ads targeting PCOS and cholesterol with the same layout = SAME root.

Use visual roots for:
  1. Briefing designers — tell them exactly what the ad should look like
  2. Identifying saturated formats — formats competitors overuse that you should avoid or own differently

Sends actual ad images + text signals to Gemini for accurate visual clustering.
Primary model: Gemini 2.5 Flash (GOOGLE_API_KEY in .env)
Fallback model: llama-3.1-8b-instant via Groq (text only)
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("visual_root_discoverer")

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = (
    "You are a senior art director specialising in Health & Wellness advertising. "
    "You will be shown actual ad images alongside their text signals. "
    "Your job is to cluster ads into 5-7 VISUAL ROOTS based purely on HOW THEY LOOK — "
    "the layout structure, what type of content fills the frame, and how the product is placed. "
    "IGNORE what the ad says, who it targets, or what condition it addresses. "
    "Two ads targeting PCOS and cholesterol with the same visual layout belong in the SAME root. "
    "Return ONLY valid JSON, no markdown, no commentary."
)

VISUAL_ROOTS_SCHEMA = """{
  "visual_roots": [
    {
      "root_id": "<kebab-case id, e.g. product-stat-callout-cards>",
      "root_name": "<FORMAT + CONTENT name, e.g. Product with Stat Callout Cards>",
      "root_emoji": "<emoji>",
      "description": "<2-3 sentences: layout structure, content shown, product placement, text treatment>",
      "layout_structure": "<two-column-split|single-image-overlay|screenshot|before-after-stacked|product-infographic|full-bleed-lifestyle|grid-stats|product-only-minimal>",
      "content_type": "<lifestyle-person|product-only|stat-callouts|food-drink-closeup|before-after|ingredient-surround|benefit-list|mechanism-diagram|text-heavy-longcopy>",
      "color_mood": "<bold-high-contrast|clean-white-clinical|warm-earthy|dark-dramatic|muted-authentic>",
      "designer_brief": "<Step-by-step visual brief: (1) background & canvas (2) hero content & placement (3) text blocks & style (4) product placement (5) supporting elements & color>",
      "saturation_signal": "<dominant|common|occasional|rare>",
      "ad_ids": ["<ad_id>"],
      "ad_count": 0
    }
  ],
  "dominant_visual_root": "<root_id>",
  "saturated_formats": ["<root_id of overused formats>"],
  "underused_formats": ["<visual format not present in these ads>"],
  "summary": "<2-3 sentences: dominant visual patterns, what is saturated, and what white space exists>"
}"""


def _extract_visual_signals(vision_ad: dict) -> dict:
    """Extract text signals for clustering — used alongside actual images."""
    fp = vision_ad.get("layout_fingerprint") or {}
    return {
        "fmt": vision_ad.get("visual_format", ""),
        "bg": fp.get("background_color", ""),
        "vis": fp.get("supporting_visual_type", ""),
        "prod": fp.get("product_zone", ""),
        "layout": (vision_ad.get("layout_template") or "")[:120],
        "scene": (vision_ad.get("scene_description") or "")[:100],
        "color": (vision_ad.get("color_palette") or "")[:60],
    }


def _get_primary_image_url(ad_id: str, scored_map: dict, vision_ad: dict | None = None) -> str:
    """Get the best available image URL for an ad — prefers Supabase URLs."""
    # Check scored map first, then vision_ad itself
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


def _existing_visual_roots_hint(existing_roots: list[dict]) -> str:
    """Build a hint block from previously discovered visual roots so names stay stable."""
    if not existing_roots:
        return ""
    lines = ["EXISTING VISUAL ROOTS (reuse these names when the format matches):"]
    for r in existing_roots:
        lines.append(f'  • [{r["root_id"]}] "{r["root_name"]}" — {r.get("description", "")[:120]}')
    lines.append("")
    return "\n".join(lines)


def build_prompt(
    vision_ads: list[dict],
    scored_map: dict,
    existing_roots: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """
    Build prompt text and return list of image items for multimodal sending.
    Returns (prompt_text, image_items) where image_items = [{idx, ad_id, url}, ...]
    """
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
        signals = _extract_visual_signals(ad)
        img_url = _get_primary_image_url(ad_id, scored_map, ad)
        idx = i + 1
        slim_ads.append({"idx": idx, "id": ad_id, **signals})
        image_items.append({"idx": idx, "ad_id": ad_id, "url": img_url})

    hint_block = _existing_visual_roots_hint(existing_roots or [])

    prompt = (
        f"You are looking at {len(slim_ads)} Health & Wellness ad images (labeled [1] to [{len(slim_ads)}]).\n"
        f"Cluster them into 5-7 VISUAL ROOTS based purely on HOW THEY LOOK.\n\n"
        + (f"{hint_block}\n" if hint_block else "")
        + "CLUSTERING RULES:\n"
        "- Group by VISUAL LAYOUT + CONTENT TYPE only\n"
        "- IGNORE: product name, condition targeted (PCOS / cholesterol / weight loss), ad copy\n"
        "- Same layout + same content type = SAME root, even if targeting different audiences\n"
        "- Minimum 3 ads per root — merge thin groups into the closest matching root\n\n"
        "KNOWN VISUAL ROOTS IN HEALTH & WELLNESS (use these names when they fit):\n"
        "  1. Product Only Minimal — product bottle centred, clean/white/plain background, minimal or no text overlay\n"
        "  2. Product with Ingredient Surround — product bottle surrounded by raw herbs, berries, or ingredient visuals\n"
        "  3. Product with Benefit Callout List — product on one side, bulleted benefits or icon+text list on the other\n"
        "  4. Stat Callout Cards — large % numbers or clinical stats (e.g. 36% reduction) are the hero visual element\n"
        "  5. Lifestyle Person Overlay — a person (woman/man) is the hero, product is secondary, text overlaid on image\n"
        "  6. Before/After Split — two panels showing a visible transformation side by side\n"
        "  7. Food/Drink Closeup — food, drink, or ingredient macro shot fills the frame; product bottle is NOT dominant\n"
        "  8. Text Heavy Long Copy — ad is mostly text (like a blog post, nurse story, or screenshot); minimal visuals\n"
        "  9. Infographic Mechanism — diagram, arrows, or body illustration explaining HOW the product works\n\n"
        "INVALID groupings: by colour only, by brand, by target audience/condition, by message\n\n"
        f"AD TEXT SIGNALS (use alongside the images for reference):\n"
        f"{json.dumps(slim_ads, separators=(',', ':'), ensure_ascii=False)}\n\n"
        f"Return ONLY a JSON object matching this schema:\n{VISUAL_ROOTS_SCHEMA}"
    )

    return prompt, image_items


def _call_llm_with_images(
    prompt: str,
    image_items: list[dict],
    vision_ads: list[dict],
    scored_map: dict,
    existing_roots: list[dict],
    google_api_key: str,
    use_gemini: bool,
) -> str:
    """Call Gemini with actual images + text (primary), or Groq text-only (fallback)."""
    if use_gemini:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=google_api_key)

        # Build multimodal contents: interleave image + label for each ad
        contents = []
        images_sent = 0
        for item in image_items:
            url = item.get("url", "")
            if url and url.startswith("http"):
                ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
                try:
                    contents.append(
                        gtypes.Part.from_uri(file_uri=url, mime_type=mime)
                    )
                    contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']}")
                    images_sent += 1
                except Exception as e:
                    logger.debug("Skipping image %s: %s", item["ad_id"], e)
                    contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']} (image unavailable)")
            else:
                contents.append(f"[{item['idx']}] Ad ID: {item['ad_id']} (no image URL)")

        contents.append(prompt)
        logger.info("Sending %d images to Gemini for visual clustering.", images_sent)

        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=gtypes.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=8192,
                        thinking_config=None,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                err = str(e)
                if "quota" in err.lower() or "429" in err or "rate" in err.lower():
                    wait = 15 * (2 ** attempt)
                    logger.warning("Gemini rate limit — waiting %ds…", wait)
                    time.sleep(wait)
                elif "payload" in err.lower() or "too large" in err.lower() or "413" in err:
                    # Too many images — retry with text only
                    logger.warning("Payload too large — retrying with text only.")
                    return _call_text_only_gemini(prompt, client)
                else:
                    logger.error("Gemini error: %s", e)
                    raise
        raise RuntimeError("Gemini rate limit exhausted after 4 attempts")

    # Groq fallback — text only
    groq_client = GroqKeyPool().client
    max_sample = 15
    current_prompt = prompt
    for attempt in range(5):
        try:
            response = groq_client.chat.completions.create(
                model=GROQ_FALLBACK_MODEL,
                max_tokens=2000,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": current_prompt},
                ],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            if "413" in err or "payload" in err.lower() or "too large" in err.lower():
                max_sample = max(5, max_sample - 5)
                logger.warning("413 — retrying with %d ads…", max_sample)
                current_prompt, _ = build_prompt(vision_ads[:max_sample], scored_map, existing_roots)
            elif "429" in err or "rate_limit" in err.lower():
                wait = 20 * (2 ** attempt)
                logger.warning("Groq rate limited — waiting %ds…", wait)
                time.sleep(wait)
            else:
                logger.error("Groq API error: %s", e)
                raise
    raise RuntimeError("Groq rate limit exhausted after 5 attempts")


def _call_text_only_gemini(prompt: str, client) -> str:
    """Fallback: call Gemini with text only when image payload is too large."""
    from google.genai import types as gtypes
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=4000,
            thinking_config=None,
        ),
    )
    return response.text.strip()


def run(
    page_label: str,
    analyzed_dir: str = "data/analyzed",
    scored_dir: str = "data/scored",
    force: bool = False,
) -> Path:
    analyzed_dir = Path(analyzed_dir)
    output_path = analyzed_dir / f"{page_label}_visual_roots.json"

    scored_path = Path(scored_dir) / f"{page_label}_scored.json"
    scored_newer = (
        scored_path.exists()
        and output_path.exists()
        and scored_path.stat().st_mtime > output_path.stat().st_mtime
    )
    if output_path.exists() and not force and not scored_newer:
        logger.info("Cache hit — skipping visual root discovery. Use --force to rerun.")
        return output_path
    if scored_newer:
        logger.info("Scored file is newer — re-clustering with updated data.")

    # Load previous roots as naming hints
    existing_roots: list[dict] = []
    if output_path.exists():
        try:
            prev = load_json(output_path)
            existing_roots = prev.get("visual_roots", [])
            if existing_roots:
                logger.info("Loaded %d existing visual roots as naming hints.", len(existing_roots))
        except Exception:
            pass

    logger.info("Waiting 10s for API rate limits to settle…")
    time.sleep(10)

    vision_path = analyzed_dir / f"{page_label}_vision_analysis.json"
    if not vision_path.exists():
        raise FileNotFoundError(f"Vision analysis not found: {vision_path}. Run vision_analyzer first.")

    vision_data = load_json(vision_path)
    vision_ads = [a for a in vision_data if not a.get("error") and a.get("visual_format")]

    if not vision_ads:
        total = len(vision_data)
        errors = sum(1 for a in vision_data if a.get("error"))
        logger.warning("No valid vision analyses found (%d total, %d errors).", total, errors)
        save_json({
            "visual_roots": [],
            "summary": (
                f"No valid image analyses found ({errors}/{total} failed). "
                "Re-run Step 4 (Analyze Images) first."
            ),
        }, output_path)
        return output_path

    scored_data = load_json(scored_path) if scored_path.exists() else {}
    scored_ads = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data
    scored_map = {a.get("ad_id"): a for a in scored_ads if a.get("ad_id")}

    logger.info("Discovering visual roots for %d ads (with images)…", len(vision_ads))

    prompt, image_items = build_prompt(vision_ads, scored_map, existing_roots)
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    use_gemini = bool(google_api_key)

    if use_gemini:
        logger.info("Using %s with %d images for visual root clustering.", GEMINI_MODEL, len(image_items))
    else:
        logger.info("GOOGLE_API_KEY not set — falling back to Groq (text only).")

    raw = _call_llm_with_images(
        prompt, image_items, vision_ads, scored_map, existing_roots, google_api_key, use_gemini
    )

    # Strip markdown fences if present
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
        roots_data = json.loads(raw)
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
    for root in roots_data.get("visual_roots", []):
        images = []
        for aid in root.get("ad_ids", []):
            imgs = ad_image_map.get(aid) or []
            if imgs:
                images.append({"ad_id": aid, "image_url": imgs[0]})
        root["ad_images"] = images

    save_json(roots_data, output_path)
    logger.info(
        "Saved %d visual roots → %s",
        len(roots_data.get("visual_roots", [])), output_path,
    )
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover visual format roots in competitor ad library")
    parser.add_argument("--page-label", required=True)
    parser.add_argument("--analyzed-dir", default="data/analyzed")
    parser.add_argument("--scored-dir", default="data/scored")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run(args.page_label, args.analyzed_dir, args.scored_dir, args.force)
