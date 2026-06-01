"""
Merge text + vision analyses, then make ONE Groq call to extract root themes.
Model: llama-3.3-70b-versatile
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("aggregator")

AGG_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a senior brand strategist and consumer psychology expert "
    "specializing in Health & Wellness marketing. "
    "Analyze the provided ad intelligence data and return ONLY valid JSON — "
    "no commentary, no markdown fences, no extra text."
)

THEMES_SCHEMA = """{
  "top_themes": [
    {
      "theme_name": "<string>",
      "frequency": <number of ads using this theme>,
      "description": "<what this theme is about>",
      "example_ad_ids": ["<ad_id>", "..."]
    }
  ],
  "dominant_emotional_angle": "<string>",
  "most_used_hook": "<string>",
  "underused_angles": ["<angle_1>", "<angle_2>"],
  "root_message": "<the single core belief or fear this brand is exploiting>"
}"""


def merge_analyses(text_analyses: list[dict], vision_analyses: list[dict]) -> list[dict]:
    vision_map = {a.get("ad_id"): a for a in vision_analyses if a.get("ad_id")}
    merged = []
    for text in text_analyses:
        ad_id = text.get("ad_id")
        combined = {**text}
        if ad_id in vision_map:
            visual = {k: v for k, v in vision_map[ad_id].items() if k != "ad_id"}
            combined["visual"] = visual
        merged.append(combined)
    return merged


def build_prompt(merged: list[dict]) -> str:
    # Sort by composite score, take top 30 to stay under Groq's token limit
    sorted_ads = sorted(merged, key=lambda a: a.get("composite_score") or 0, reverse=True)
    sample = sorted_ads[:30]

    slim = []
    for ad in sample:
        visual = ad.get("visual") or {}
        slim.append({
            "id": ad.get("ad_id"),
            "hook": ad.get("hook_type"),
            "tone": ad.get("emotional_tone"),
            "claim": (ad.get("core_claim") or "")[:80],
            "cta": ad.get("cta_style"),
            "headline": (ad.get("ad_creative_link_title") or "")[:60],
            "days": ad.get("run_duration_days"),
            "vformat": visual.get("visual_format"),
            "story_arc": (visual.get("story_arc") or "")[:80],
            "trigger": (visual.get("emotional_trigger") or "")[:80],
        })

    summaries = json.dumps(slim, separators=(",", ":"), ensure_ascii=False)
    return (
        f"Below is ad intelligence data (top {len(slim)} ads by score) for a Health & Wellness competitor.\n\n"
        f"AD DATA:\n{summaries}\n\n"
        f"Identify dominant themes, emotional angles, and strategic patterns across these ads.\n\n"
        f"Return ONLY a JSON object matching this schema:\n{THEMES_SCHEMA}\n\n"
        f"Be specific and actionable. 'underused_angles' should highlight real positioning gaps."
    )


def print_summary(themes: dict) -> None:
    print("\n" + "=" * 60)
    print("  COMPETITOR AD INTELLIGENCE — AGGREGATED THEMES")
    print("=" * 60)
    print(f"\n ROOT MESSAGE:\n  {themes.get('root_message', 'N/A')}")
    print(f"\n DOMINANT EMOTIONAL ANGLE:  {themes.get('dominant_emotional_angle', 'N/A')}")
    print(f" MOST USED HOOK:            {themes.get('most_used_hook', 'N/A')}")
    underused = themes.get("underused_angles", [])
    if underused:
        print("\n UNDERUSED ANGLES (your opportunities):")
        for angle in underused:
            print(f"  • {angle}")
    for t in themes.get("top_themes", []):
        print(f"\n  [{t.get('frequency','?')} ads]  {t.get('theme_name','')}")
        print(f"  {t.get('description','')}")
        ids = t.get("example_ad_ids", [])
        if ids:
            print(f"  Examples: {', '.join(str(i) for i in ids[:3])}")
    print("\n" + "=" * 60 + "\n")


def run(
    page_label: str,
    analyzed_dir: str = "data/analyzed",
    force: bool = False,
) -> Path:
    analyzed_dir = Path(analyzed_dir)
    text_path = analyzed_dir / f"{page_label}_text_analysis.json"
    vision_path = analyzed_dir / f"{page_label}_vision_analysis.json"
    output_path = analyzed_dir / f"{page_label}_aggregated_themes.json"

    if output_path.exists() and not force:
        logger.info("Cache hit — skipping aggregation. Use --force to rerun.")
        themes = load_json(output_path)
        print_summary(themes)
        return output_path

    if not text_path.exists():
        raise FileNotFoundError(f"Text analysis not found: {text_path}. Run text_analyzer first.")

    text_analyses = load_json(text_path)
    vision_analyses = load_json(vision_path) if vision_path.exists() else []

    logger.info(
        "Merging %d text + %d vision analyses…",
        len(text_analyses), len(vision_analyses),
    )
    merged = merge_analyses(text_analyses, vision_analyses)
    prompt = build_prompt(merged)

    logger.info("Sending aggregation prompt to Groq (model: %s)…", AGG_MODEL)
    client = GroqKeyPool().client

    import time
    response = None
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=AGG_MODEL,
                max_tokens=2048,
                temperature=0.3,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            break
        except Exception as e:
            err = str(e)
            if "413" in err or "too large" in err.lower():
                raise RuntimeError("Prompt too large (413) — reduce ad count in build_prompt.") from e
            elif "429" in err or "rate_limit" in err.lower():
                wait = 20 * (2 ** attempt)
                logger.warning("Rate limited — waiting %ds…", wait)
                time.sleep(wait)
            else:
                raise

    if response is None:
        raise RuntimeError("Groq API call failed after retries.")

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        themes = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse aggregation response: %s\nRaw:\n%s", e, raw[:500])
        raise

    save_json(themes, output_path)
    logger.info("Saved aggregated themes → %s", output_path)
    print_summary(themes)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Aggregate ad themes with Groq")
    parser.add_argument("--page-label", required=True)
    parser.add_argument("--analyzed-dir", default="data/analyzed")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run(args.page_label, args.analyzed_dir, args.force)
