"""
Analyze ad images via Gemini 2.5 Flash (primary) or Groq Vision (fallback).

If GOOGLE_API_KEY is set in .env → uses Gemini 2.5 Flash (better layout understanding).
Otherwise → falls back to Groq llama-4-scout vision model.
"""

import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("vision_analyzer")

GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are an expert visual advertising analyst and creative director for Health & Wellness brands. "
    "Deeply analyze ad images — extract the narrative, emotional strategy, and visual storytelling "
    "technique so another creative can replicate the same approach for a different product. "
    "Return ONLY valid JSON — no commentary, no markdown fences, no extra text."
)

VISION_SCHEMA = """{
  "ad_id": "<string>",
  "layout_fingerprint": {
    "background_color": "red | white | dark | earthy-green | earthy-brown | blue | gradient-dark | outdoor-scene | yellow | orange | other",
    "supporting_visual_type": "lifestyle-person | ingredient-shot | mechanism-illustration | before-after | ugc-person | outdoor-scene | product-only | text-only",
    "product_zone": "bottom-center | bottom-right | bottom-left | center | held-in-hand | not-visible | right | left",
    "headline_zone": "top | center-left | center | overlay-bottom | bottom | not-present",
    "overlay_type": "text-on-photo | text-on-solid-color | infographic-white | minimal | text-heavy"
  },
  "visual_format": "before-after | lifestyle | product-infographic | testimonial | ugc | mechanism-explainer | benefit-checklist | text-heavy | product-only",
  "layout_template": "<exact spatial layout: TOP/CENTER/BOTTOM zones, what sits where>",
  "scene_description": "<2-3 sentences: every major element, left to right, top to bottom>",
  "mechanism_element": "<body part/organ/scientific illustration shown, or 'none'>",
  "product_element": "<how the product appears — bottle, pack, held, etc. — or 'not visible'>",
  "benefit_presentation": "<how benefits are shown — bullets, checkmarks, callout cards, etc. — or 'none'>",
  "headline_style": "<headline text style — font weight, color, position>",
  "story_arc": "<the narrative this image tells in one sentence>",
  "emotional_trigger": "<emotion evoked and how>",
  "color_palette": "<dominant colors and mood>",
  "replication_guide": "<step-by-step to recreate: (1) background (2) headline (3) hero visual (4) product (5) benefits (6) CTA>"
}"""


def load_image_as_base64(source: str, timeout: int = 20) -> tuple[str, str]:
    path = Path(source)
    if path.exists():
        data = path.read_bytes()
        suffix = path.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
        return base64.standard_b64encode(data).decode("utf-8"), mime

    headers = {"User-Agent": "Mozilla/5.0 (compatible; AdIntelBot/1.0)"}
    resp = requests.get(source, timeout=timeout, headers=headers)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        raise ValueError(f"Non-image content type: {content_type}")
    return base64.standard_b64encode(resp.content).decode("utf-8"), content_type


def _extract_json(raw: str) -> str:
    """Extract the outermost JSON object from a string that may contain markdown or extra text."""
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return ""
    return raw[start:end]


def _build_image_part(image_urls: list, ad_id: str):
    """
    Build a Gemini image Part from the first working URL.
    - Remote URLs (http/https): passed directly via from_uri — no download needed.
    - Local file paths: read and base64-encode as before.
    Returns (part, used_url) or (None, None) on failure.
    """
    from google.genai import types

    for url in image_urls:
        url_str = str(url)
        # ── Remote URL: let Gemini fetch it directly ──────────────────────────
        if url_str.startswith("http://") or url_str.startswith("https://"):
            # Detect mime type from extension; default to jpeg
            ext = url_str.split("?")[0].rsplit(".", 1)[-1].lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp",
                    "gif": "image/gif"}.get(ext, "image/jpeg")
            try:
                return types.Part.from_uri(file_uri=url_str, mime_type=mime), url_str
            except Exception as e:
                logger.debug("from_uri failed (%s): %s — trying base64", url_str[:80], e)
                # Fall through to base64 download below

        # ── Local file or failed URI: download + base64 ───────────────────────
        try:
            image_data, media_type = load_image_as_base64(url_str)
            return types.Part.from_bytes(
                data=base64.b64decode(image_data),
                mime_type=media_type,
            ), url_str
        except Exception as e:
            logger.debug("Image load failed (%s): %s", url_str[:80], e)

    return None, None


def analyze_with_gemini(ad: dict, google_api_key: str) -> dict:
    """Analyze a single ad image using Gemini 2.5 Flash.

    Uses from_uri for remote URLs (no download) so this works on hosted servers
    that don't have local image files. Falls back to base64 for local paths.
    """
    from google import genai
    from google.genai import types

    ad_id = ad.get("ad_id", "unknown")
    image_urls = (
        ad.get("ad_image_urls")
        or ([ad["primary_image_url"]] if ad.get("primary_image_url") else [])
        or ([ad["ad_snapshot_url"]] if ad.get("ad_snapshot_url") else [])
    )

    if not image_urls:
        return {"ad_id": ad_id, "error": "no_image_url"}

    image_part, used_url = _build_image_part(image_urls, ad_id)
    if image_part is None:
        return {"ad_id": ad_id, "error": "image_fetch_failed"}

    client = genai.Client(api_key=google_api_key)

    prompt = (
        f"Reverse-engineer this Health & Wellness ad image (ad_id: {ad_id}) "
        f"so a designer can recreate the same visual template for a different product.\n\n"
        f"Be precise about spatial layout, every visual element, and exact text visible.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{VISION_SCHEMA}\n\n"
        f'Use "{ad_id}" as the value for the ad_id field.'
    )

    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[image_part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_output_tokens=2048,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )

            raw = response.text.strip()
            extracted = _extract_json(raw)
            if not extracted:
                logger.error("No JSON in Gemini response for ad %s. Raw: %s", ad_id, raw[:300])
                return {"ad_id": ad_id, "error": "no_json_in_response"}

            return json.loads(extracted)

        except json.JSONDecodeError as e:
            logger.error("JSON parse error for ad %s: %s\nRaw:\n%s", ad_id, e, raw[:400])
            return {"ad_id": ad_id, "error": "parse_failed"}
        except Exception as e:
            err = str(e)
            if "quota" in err.lower() or "429" in err or "rate" in err.lower():
                wait = 15 * (2 ** attempt)
                logger.warning("Gemini rate limit — waiting %ds…", wait)
                time.sleep(wait)
            else:
                logger.error("Gemini error for ad %s: %s", ad_id, e)
                return {"ad_id": ad_id, "error": f"gemini_failed: {e}"}

    return {"ad_id": ad_id, "error": "gemini_rate_limit_exhausted"}


def analyze_with_groq(pool: GroqKeyPool, ad: dict) -> dict:
    """Analyze a single ad image using Groq Vision (fallback)."""
    ad_id = ad.get("ad_id", "unknown")
    image_urls = (
        ad.get("ad_image_urls")
        or ([ad["primary_image_url"]] if ad.get("primary_image_url") else [])
        or ([ad["ad_snapshot_url"]] if ad.get("ad_snapshot_url") else [])
    )

    if not image_urls:
        return {"ad_id": ad_id, "error": "no_image_url"}

    image_data, media_type = None, None
    for url in image_urls:
        try:
            image_data, media_type = load_image_as_base64(url)
            break
        except Exception as e:
            logger.debug("Image load failed (%s): %s", str(url)[:80], e)

    if image_data is None:
        return {"ad_id": ad_id, "error": "image_fetch_failed"}

    prompt = (
        f"Reverse-engineer this Health & Wellness ad image (ad_id: {ad_id}) "
        f"so a designer can recreate the same visual template for a different product.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{VISION_SCHEMA}\n\n"
        f'Use "{ad_id}" as the value for the ad_id field.'
    )

    pool.reset_rotation()
    while True:
        try:
            response = pool.client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                max_tokens=1024,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                        {"type": "text", "text": prompt},
                    ]},
                ],
            )
            break
        except Exception as e:
            err = str(e)
            if GroqKeyPool.is_retriable(err):
                logger.warning("Groq API error (%s) — trying next key…", err[:80])
                if not pool.rotate():
                    return {"ad_id": ad_id, "error": "all_keys_exhausted"}
            else:
                logger.error("Groq API error for ad %s: %s", ad_id, e)
                return {"ad_id": ad_id, "error": f"api_failed: {e}"}

    raw = response.choices[0].message.content.strip()
    extracted = _extract_json(raw)
    if not extracted:
        return {"ad_id": ad_id, "error": "parse_failed", "raw": raw[:300]}
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        return {"ad_id": ad_id, "error": "parse_failed", "raw": raw[:300]}


def run(scored_path: str | Path, output_dir: str = "data/analyzed", force: bool = False) -> Path:
    scored_path = Path(scored_path)
    page_label = scored_path.stem.replace("_scored", "")
    output_path = Path(output_dir) / f"{page_label}_vision_analysis.json"

    data = load_json(scored_path)
    ads = data.get("scored_ads", data) if isinstance(data, dict) else data
    image_ads = [a for a in ads if a.get("ad_image_urls") or a.get("primary_image_url")]

    # Load existing results and skip already-analyzed ad_ids (incremental)
    existing_results: list[dict] = []
    analyzed_ids: set[str] = set()
    if output_path.exists() and not force:
        existing_results = load_json(output_path)
        analyzed_ids = {r["ad_id"] for r in existing_results if r.get("ad_id") and not r.get("error")}

    new_image_ads = [a for a in image_ads if a.get("ad_id") not in analyzed_ids]

    if not new_image_ads:
        logger.info("Vision analysis: all %d image ads already analyzed — skipping.", len(image_ads))
        return output_path

    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    use_gemini = bool(google_api_key)

    if use_gemini:
        logger.info("Using Gemini 2.5 Flash — %d new ads to analyze (%d cached).", len(new_image_ads), len(analyzed_ids))
        try:
            from google import genai  # noqa: F401
        except ImportError:
            logger.error("google-genai not installed. Run: pip install google-genai")
            raise
    else:
        logger.info("GOOGLE_API_KEY not set — falling back to Groq vision. %d new ads.", len(new_image_ads))

    groq_pool = GroqKeyPool() if not use_gemini else None
    new_results: list[dict] = []

    for i, ad in enumerate(new_image_ads, 1):
        logger.info(
            "Vision %d / %d (ad_id: %s) [%s]…",
            i, len(new_image_ads), ad.get("ad_id"),
            "Gemini" if use_gemini else "Groq",
        )
        if use_gemini:
            result = analyze_with_gemini(ad, google_api_key)
            if i < len(new_image_ads):
                time.sleep(4)  # Gemini free tier: 15 RPM
        else:
            result = analyze_with_groq(groq_pool, ad)
            if i < len(new_image_ads):
                time.sleep(3)

        new_results.append(result)

    all_results = existing_results + new_results
    save_json(all_results, output_path)
    logger.info("Saved vision analysis (%d total, %d new) → %s", len(all_results), len(new_results), output_path)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Vision-analyze ad images with Gemini or Groq")
    parser.add_argument("--scored-file", required=True)
    parser.add_argument("--output-dir", default="data/analyzed")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run(args.scored_file, args.output_dir, args.force)
