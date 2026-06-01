"""
Discover creative "roots" — persuasion strategy archetypes shared across competitor ads.

A root = a reusable CREATIVE STRATEGY: same psychological mechanism + same structural format.
Examples: "VS Comparison Root", "Authority Notes Root", "Hidden Math Root", "Myth Buster Root".

IMPORTANT: Roots are defined by HOW THE AD PERSUADES, not how it looks.
Two ads share a root if a strategist says "these use the same mechanism to convince the audience."

Reads text_analysis + vision_analysis, sends to LLM for clustering into 5-7 strategy roots,
saves discovered roots for user confirmation.

Model: llama-3.3-70b-versatile
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("root_discoverer")

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a senior creative strategist and advertising psychologist specializing in Health & Wellness brands. "
    "Your job is to find the 5-7 core CREATIVE STRATEGY ROOTS that a competitor reuses across their ad library. "
    "A ROOT is defined by HOW THE AD PERSUADES — the psychological mechanism it uses to convince the audience. "
    "Two ads belong in the same root if a strategist would say 'these use the same mechanism to make the audience believe and act'. "
    "PRIMARY signals (must match): persuasion_angle + content_format "
    "(e.g. both open with a comparison grid + exploit fear-of-loss). "
    "SECONDARY signals: hook_mechanism + proof_style + emotional_tone. "
    "WRONG: grouping ads by topic (e.g. 'all weight-loss ads') — that is a THEME, not a root. "
    "WRONG: grouping by visual style (e.g. 'all red background ads') — that is a visual template, not a root. "
    "RIGHT: 'all ads that place the audience's current behavior next to a better alternative and let the contrast do the convincing' — that is a strategy root (VS Comparison Root). "
    "RIGHT: 'all ads that borrow a third-party voice (doctor, nutritionist, expert notes) so the product appears as a recommendation not an ad' — that is a strategy root (Authority Borrow Root). "
    "Return ONLY valid JSON — no commentary, no markdown fences, no extra text."
)

ROOTS_SCHEMA = """{
  "roots": [
    {
      "root_id": "<short kebab-case id based on persuasion strategy, e.g. vs-comparison, authority-borrow, hidden-math, myth-buster, identity-shift, relatable-moment, permission-give>",
      "root_name": "<memorable strategy name describing the PERSUASION ANGLE, e.g. 'VS Comparison Root', 'Authority Borrow Root', 'Hidden Math Root', 'Myth Buster Root'>",
      "root_emoji": "<single emoji that represents the strategy feel>",
      "description": "<2-3 sentences: what is the creative strategy, how does it persuade the audience, what psychological mechanism does it exploit — then ONE sentence on the typical structural format used>",
      "strategy_template": {
        "persuasion_angle": "<the core mechanism — comparison | authority-borrow | shock-math | myth-bust | identity-shift | relatable-moment | fear-reveal | permission-give | social-proof>",
        "content_format": "<the structural format — vs-grid | fake-notes | stat-reveal | story-narrative | testimonial | checklist | question-answer | before-after | myth-then-truth>",
        "hook_mechanism": "<how it opens — e.g. 'places audience in a familiar daily moment' | 'states a belief the audience holds then challenges it' | 'reveals a hidden number they never calculated'>",
        "psychological_trigger": "<the cognitive bias or emotion activated — e.g. 'loss aversion: counting what they silently lose every day' | 'authority bias: expert tells them what to do' | 'cognitive dissonance: they believed X but the ad shows X is wrong'>",
        "audience_entry_point": "<where the audience mentally is when this root hits them — e.g. 'frustrated that weight won't go despite effort' | 'feeling guilty after an oily meal' | 'curious but skeptical about the product'>",
        "proof_mechanism": "<how the claim is backed — numbers/calculation | expert endorsement | before-after visual | testimonial | logical demonstration | scientific claim>"
      },
      "messaging_pattern": {
        "hook_type": "<pain-point | curiosity | social-proof | aspiration | myth-bust | shock>",
        "emotional_tone": "<fear | hope | guilt | trust | surprise | relief | pride>",
        "typical_headline_structure": "<the headline pattern, e.g. 'You thought [X]. It wasn\\'t.' or 'Your [thing] right now vs [thing] with [product]' or '[Expert] said this about [behavior]'>",
        "cta_style": "<soft | direct | discount-led | urgency>"
      },
      "replication_guide": "<step-by-step STRATEGY instructions to recreate this root for a new product: (1) identify the belief/problem/moment to open with, (2) set up the contrast or reveal, (3) present the proof naturally, (4) connect to your product as the answer, (5) close with the emotional payoff or action>",
      "why_it_works": "<the psychological reason this root cuts through — what makes it feel less like an ad, stop the scroll, or create emotional resonance that generic benefit ads miss>",
      "ad_ids": ["<ad_id of every ad that belongs to this root>"],
      "ad_count": <number of ads in this root>
    }
  ],
  "dominant_root": "<root_id of the most commonly used root>",
  "underused_roots": ["<strategy roots NOT found in these fetched ads — real opportunities to differentiate>"],
  "summary": "<2-3 sentences: what persuasion strategies does this competitor rely on most, and what gap does that reveal that you can exploit>"
}"""


def _extract_strategy_signals(ad: dict, visual: dict) -> dict:
    """Extract strategy-level signals from text and vision analysis."""
    return {
        "hook_type": ad.get("hook_type", ""),
        "emotional_tone": ad.get("emotional_tone", ""),
        "core_claim": (ad.get("core_claim") or "")[:100],
        "cta_style": ad.get("cta_style", ""),
        "headline": (ad.get("ad_creative_link_title") or "")[:80],
        "body": (ad.get("ad_creative_body") or "")[:150],
        "visual_format": visual.get("visual_format", ""),
        "story_arc": (visual.get("story_arc") or "")[:100],
        "emotional_trigger": (visual.get("emotional_trigger") or "")[:100],
    }


def _existing_roots_hint(existing_roots: list[dict]) -> str:
    """Build a hint block from previously discovered roots so names stay stable."""
    if not existing_roots:
        return ""
    lines = ["EXISTING STRATEGY ROOTS (reuse these names when the pattern matches):"]
    for r in existing_roots:
        lines.append(f'  • [{r["root_id"]}] "{r["root_name"]}" — {r.get("description", "")[:120]}')
    lines.append("")
    return "\n".join(lines)


def build_prompt(merged_ads: list[dict], existing_roots: list[dict] | None = None) -> str:
    sorted_ads = sorted(merged_ads, key=lambda a: a.get("composite_score") or 0, reverse=True)
    sample = sorted_ads[:30]

    slim_ads = []
    for ad in sample:
        visual = ad.get("_visual") or ad.get("visual") or {}
        signals = _extract_strategy_signals(ad, visual)
        slim_ads.append({"id": ad.get("ad_id"), **signals})

    hint_block = _existing_roots_hint(existing_roots or [])

    return (
        f"Cluster these {len(slim_ads)} competitor Health & Wellness ads into 5-7 creative STRATEGY ROOTS.\n\n"
        + (f"{hint_block}\n" if hint_block else "")
        + f"CRITICAL: Cluster by PERSUASION MECHANISM, not by topic or visual style.\n"
        f"Step 1 — Identify what psychological mechanism each ad uses to convince the audience.\n"
        f"Step 2 — Group ads that use the same mechanism + structural format.\n"
        f"Step 3 — Name the root after the STRATEGY, not the visual (e.g. 'VS Comparison Root', not 'Red Background Root').\n\n"
        f"EXAMPLES OF VALID ROOTS:\n"
        f"✅ 'VS Comparison Root' — ads that place the audience's current behavior next to a better alternative.\n"
        f"✅ 'Authority Borrow Root' — ads that use a doctor/nutritionist/expert note so the product appears as trusted advice.\n"
        f"✅ 'Hidden Math Root' — ads that reveal a number the audience never calculated to make an invisible problem feel urgent.\n"
        f"✅ 'Myth Buster Root' — ads that open by stating a false belief the audience holds, then flip it.\n"
        f"✅ 'Relatable Moment Root' — ads that drop the audience into a scene they live every day.\n\n"
        f"EXAMPLES OF INVALID ROOTS:\n"
        f"❌ 'All weight-loss ads' — topic/theme, not a persuasion strategy.\n"
        f"❌ 'All red background ads' — visual template, not a strategy.\n\n"
        f"ADS:\n{json.dumps(slim_ads, separators=(',', ':'), ensure_ascii=False)}\n\n"
        f"Rules:\n"
        f"- Assign every ad to exactly one root\n"
        f"- Minimum 3 ads per root — if a pattern has fewer than 3 ads, merge it into the closest existing root\n"
        f"- Reuse an existing root name (from EXISTING STRATEGY ROOTS above) when 3+ ads match its pattern\n"
        f"- Only create a NEW root if 3+ ads clearly don't fit any existing root\n"
        f"- Root names must describe the STRATEGY (e.g. 'Hidden Math Root', 'Myth Buster Root')\n"
        f"- replication_guide must be step-by-step STRATEGY instructions, not visual instructions\n"
        f"- Include ALL ad ids in each root's ad_ids array\n"
        f"- 'underused_roots' must list real strategy gaps not present in these ads\n\n"
        f"Return ONLY a JSON object matching this schema:\n{ROOTS_SCHEMA}"
    )


def run(
    page_label: str,
    analyzed_dir: str = "data/analyzed",
    scored_dir: str = "data/scored",
    force: bool = False,
) -> Path:
    analyzed_dir = Path(analyzed_dir)
    output_path = analyzed_dir / f"{page_label}_roots.json"

    scored_path_check = Path(scored_dir) / f"{page_label}_scored.json"
    scored_newer = (
        scored_path_check.exists()
        and output_path.exists()
        and scored_path_check.stat().st_mtime > output_path.stat().st_mtime
    )
    if output_path.exists() and not force and not scored_newer:
        logger.info("Cache hit — skipping root discovery. Use --force to rerun.")
        return output_path
    if scored_newer:
        logger.info("Scored file is newer than roots — re-clustering with updated master data.")

    text_path = analyzed_dir / f"{page_label}_text_analysis.json"
    vision_path = analyzed_dir / f"{page_label}_vision_analysis.json"
    scored_path = Path(scored_dir) / f"{page_label}_scored.json"

    if not text_path.exists():
        raise FileNotFoundError(f"Text analysis not found: {text_path}. Run text_analyzer first.")

    text_data = load_json(text_path)
    vision_data = load_json(vision_path) if vision_path.exists() else []
    scored_data = load_json(scored_path) if scored_path.exists() else {}
    scored_ads = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data

    vision_map = {a.get("ad_id"): a for a in vision_data if a.get("ad_id")}
    scored_map = {a.get("ad_id"): a for a in scored_ads if a.get("ad_id")}

    merged = []
    for ad in text_data:
        aid = ad.get("ad_id")
        row = {**scored_map.get(aid, {}), **ad}
        if aid in vision_map:
            row["_visual"] = vision_map[aid]
        merged.append(row)

    # Load previous roots as naming hints so root names stay stable across runs
    existing_roots: list[dict] = []
    if output_path.exists():
        try:
            prev = load_json(output_path)
            existing_roots = prev.get("roots", [])
            if existing_roots:
                logger.info("Loaded %d existing roots as naming hints.", len(existing_roots))
        except Exception:
            pass

    logger.info("Discovering strategy roots for %d ads…", len(merged))

    prompt = build_prompt(merged, existing_roots)
    client = GroqKeyPool().client

    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                max_tokens=4000,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            break
        except Exception as e:
            err = str(e)
            if "413" in err or "payload" in err.lower() or "too large" in err.lower():
                raise RuntimeError("Prompt too large for Groq API (413). Reduce ad count.") from e
            elif "429" in err or "rate_limit" in err.lower():
                wait = 20 * (2 ** attempt)
                logger.warning("Rate limited — waiting %ds…", wait)
                time.sleep(wait)
            else:
                logger.error("Groq API error: %s", e)
                raise
    else:
        raise RuntimeError("Rate limit exhausted after 5 attempts")

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        roots_data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("JSON parse failed: %s\nRaw:\n%s", e, raw[:500])
        raise

    # Attach image paths for each root so the dashboard can render examples
    ad_image_map = {
        a.get("ad_id"): (a.get("ad_image_urls") or ([a["primary_image_url"]] if a.get("primary_image_url") else []))
        for a in scored_ads
    }
    for root in roots_data.get("roots", []):
        images = []
        for aid in root.get("ad_ids", []):
            imgs = ad_image_map.get(aid) or []
            if imgs:
                images.append({"ad_id": aid, "image_url": imgs[0]})
        root["ad_images"] = images

    save_json(roots_data, output_path)
    logger.info(
        "Saved %d strategy roots → %s",
        len(roots_data.get("roots", [])), output_path,
    )
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Discover creative strategy roots in competitor ad library")
    parser.add_argument("--page-label", required=True)
    parser.add_argument("--analyzed-dir", default="data/analyzed")
    parser.add_argument("--scored-dir", default="data/scored")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run(args.page_label, args.analyzed_dir, args.scored_dir, args.force)
