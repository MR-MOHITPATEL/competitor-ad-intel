"""
Discover visual roots — format + content-type archetypes shared across competitor ads.

A visual root = a reusable VISUAL TEMPLATE: same ad layout structure + same type of content shown.
Examples: "Two-Column Food Comparison Split", "Full-Screen Person With Text Overlay", "Notes Screenshot".

IMPORTANT: Visual roots are defined by HOW THE AD LOOKS, not how it persuades.
This is a completely separate layer from strategy roots.
Each ad independently belongs to one visual root AND one strategy root.

Use visual roots for:
  1. Briefing designers — tell them exactly what the ad should look like
  2. Identifying saturated formats — formats competitors overuse that you should avoid or own differently

Reads vision_analysis, sends to Gemini 2.5 Flash (primary) or Groq (fallback) for clustering
into 5-7 visual roots, saves to {page_label}_visual_roots.json.

Primary model: Gemini 2.5 Flash (GOOGLE_API_KEY in .env)
Fallback model: llama-3.1-8b-instant via Groq
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("visual_root_discoverer")

GEMINI_MODEL = "gemini-3.5-flash"
GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"

SYSTEM_PROMPT = (
    "You are an art director. Cluster Health & Wellness ads into 5-7 VISUAL ROOTS. "
    "A root = same layout structure + same content type (e.g. two-column-split + food-comparison). "
    "Cluster by HOW IT LOOKS, not what it says. Return ONLY valid JSON, no markdown."
)

VISUAL_ROOTS_SCHEMA = """{
  "visual_roots": [
    {
      "root_id": "<kebab-case id, e.g. two-col-food-split>",
      "root_name": "<FORMAT + CONTENT name, e.g. Two-Column Food Comparison Split>",
      "root_emoji": "<emoji>",
      "description": "<2-3 sentences: layout structure, content shown, product placement, text treatment>",
      "layout_structure": "<two-column-split|single-image-overlay|screenshot|before-after-stacked|product-infographic|full-bleed-lifestyle|grid-stats>",
      "content_type": "<food-comparison|lifestyle-person|product-only|notes-checklist|body-transformation|ingredient-shot|mechanism-illustration|text-heavy>",
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
    """Extract visual signals for clustering — fingerprint + key descriptive fields."""
    fp = vision_ad.get("layout_fingerprint") or {}
    return {
        "fmt": vision_ad.get("visual_format", ""),
        "bg": fp.get("background_color", ""),
        "vis": fp.get("supporting_visual_type", ""),
        "prod": fp.get("product_zone", ""),
        "ov": fp.get("overlay_type", ""),
        "layout": (vision_ad.get("layout_template") or "")[:120],
        "scene": (vision_ad.get("scene_description") or "")[:100],
        "headline": (vision_ad.get("headline_style") or "")[:80],
        "color": (vision_ad.get("color_palette") or "")[:60],
    }


def _existing_visual_roots_hint(existing_roots: list[dict]) -> str:
    """Build a hint block from previously discovered visual roots so names stay stable."""
    if not existing_roots:
        return ""
    lines = ["EXISTING VISUAL ROOTS (reuse these names when the format matches):"]
    for r in existing_roots:
        lines.append(f'  • [{r["root_id"]}] "{r["root_name"]}" — {r.get("description", "")[:120]}')
    lines.append("")
    return "\n".join(lines)


def build_prompt(vision_ads: list[dict], scored_map: dict, existing_roots: list[dict] | None = None) -> str:
    sorted_ads = sorted(
        vision_ads,
        key=lambda a: (scored_map.get(a.get("ad_id", ""), {}) or {}).get("composite_score") or 0,
        reverse=True,
    )
    sample = sorted_ads[:30]

    slim_ads = []
    for ad in sample:
        signals = _extract_visual_signals(ad)
        slim_ads.append({"id": ad.get("ad_id"), **signals})

    hint_block = _existing_visual_roots_hint(existing_roots or [])

    return (
        f"Cluster these {len(slim_ads)} Health & Wellness ad visuals into 5-7 VISUAL ROOTS.\n"
        + (f"\n{hint_block}\n" if hint_block else "")
        + f"Cluster by VISUAL FORMAT + CONTENT TYPE together (not by message).\n"
        f"Each root = same layout structure + same type of content shown.\n\n"
        f"VALID roots: 'Two-Column Food Split', 'Notes Screenshot', 'Full-Screen Person Overlay', 'Product With Stat Cards'\n"
        f"INVALID: topic-based ('all weight-loss ads') or color-only ('all red ads')\n\n"
        f"ADS:\n{json.dumps(slim_ads, separators=(',', ':'), ensure_ascii=False)}\n\n"
        f"Rules:\n"
        f"- Assign every ad to exactly one root\n"
        f"- Minimum 3 ads per root — merge thin patterns into the closest existing root\n"
        f"- Reuse an existing root name (from EXISTING VISUAL ROOTS above) when 3+ ads match its format\n"
        f"- Only create a NEW root if 3+ ads clearly don't fit any existing root\n"
        f"- Names describe FORMAT+CONTENT (e.g. 'Two-Column Food Split', not 'Red Ads')\n"
        f"Return ONLY a JSON object matching this schema:\n{VISUAL_ROOTS_SCHEMA}"
    )


def _call_llm(
    prompt: str,
    vision_ads: list[dict],
    scored_map: dict,
    existing_roots: list[dict],
    google_api_key: str,
    use_gemini: bool,
) -> str:
    """Call Gemini (primary) or Groq (fallback) and return raw text response."""
    if use_gemini:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(api_key=google_api_key)
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=gtypes.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.2,
                        max_output_tokens=3000,
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
                else:
                    logger.error("Gemini error: %s", e)
                    raise
        raise RuntimeError("Gemini rate limit exhausted after 4 attempts")

    # Groq fallback
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
                if max_sample < 5:
                    raise RuntimeError("Prompt still too large after reducing to 5 ads.") from e
                logger.warning("413 — retrying with %d ads…", max_sample)
                current_prompt = build_prompt(vision_ads[:max_sample], scored_map, existing_roots)
            elif "429" in err or "rate_limit" in err.lower():
                wait = 20 * (2 ** attempt)
                logger.warning("Groq rate limited — waiting %ds…", wait)
                time.sleep(wait)
            else:
                logger.error("Groq API error: %s", e)
                raise
    raise RuntimeError("Groq rate limit exhausted after 5 attempts")


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
        logger.info("Scored file is newer than visual roots — re-clustering with updated master data.")

    # Load previous roots as naming hints so root names stay stable across runs
    existing_roots: list[dict] = []
    if output_path.exists():
        try:
            prev = load_json(output_path)
            existing_roots = prev.get("visual_roots", [])
            if existing_roots:
                logger.info("Loaded %d existing visual roots as naming hints.", len(existing_roots))
        except Exception:
            pass

    # Brief pause so rate-limit windows from vision analysis (heavy image calls) can reset
    logger.info("Waiting 10s for API rate limits to settle before visual root discovery…")
    time.sleep(10)

    vision_path = analyzed_dir / f"{page_label}_vision_analysis.json"

    if not vision_path.exists():
        raise FileNotFoundError(f"Vision analysis not found: {vision_path}. Run vision_analyzer first.")

    vision_data = load_json(vision_path)
    # Filter out failed vision analyses
    vision_ads = [a for a in vision_data if not a.get("error") and a.get("visual_format")]

    if not vision_ads:
        total = len(vision_data)
        errors = sum(1 for a in vision_data if a.get("error"))
        logger.warning(
            "No valid vision analyses found (%d total, %d errors) — "
            "run Step 4 (Analyze Images) first, or re-fetch ads if images are expired.",
            total, errors,
        )
        save_json({
            "visual_roots": [],
            "summary": (
                f"No valid image analyses found ({errors}/{total} failed). "
                "Re-run Step 4 (Analyze Images) — images may have expired and need a fresh fetch."
            ),
        }, output_path)
        return output_path

    scored_data = load_json(scored_path) if scored_path.exists() else {}
    scored_ads = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data
    scored_map = {a.get("ad_id"): a for a in scored_ads if a.get("ad_id")}

    logger.info("Discovering visual roots for %d vision-analyzed ads…", len(vision_ads))

    prompt = build_prompt(vision_ads, scored_map, existing_roots)
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    use_gemini = bool(google_api_key)

    if use_gemini:
        logger.info("Using Gemini 2.5 Flash for visual root clustering.")
    else:
        logger.info("GOOGLE_API_KEY not set — falling back to Groq for visual root clustering.")

    raw = _call_llm(prompt, vision_ads, scored_map, existing_roots, google_api_key, use_gemini)

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

    # Attach image URLs for dashboard rendering — prefer permanent Supabase URLs
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
