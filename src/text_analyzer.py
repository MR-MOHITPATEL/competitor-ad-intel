"""
Batch-analyze ad copy via Groq API — one call per 10 ads to minimize cost.
Model: llama-3.3-70b-versatile (fast, strong JSON instruction-following)
Results are cached; use --force to rerun.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import GroqKeyPool, get_logger, load_json, save_json

logger = get_logger("text_analyzer")

BATCH_SIZE = 10
INTER_BATCH_DELAY = 4   # seconds between batches to stay under rate limit
TEXT_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are an expert direct-response copywriter and marketing analyst "
    "specializing in Health & Wellness brands. "
    "Analyze the provided ad creatives and return ONLY valid JSON — "
    "no commentary, no markdown fences, no extra text."
)

ANALYSIS_SCHEMA = """{
  "ad_id": "<string>",
  "hook_type": "pain-point | aspiration | social-proof | curiosity | urgency",
  "emotional_tone": "fear | hope | trust | excitement | guilt",
  "core_claim": "<one sentence summary of the main promise>",
  "target_audience_signal": "<who this ad seems to target>",
  "cta_style": "soft | direct | discount-led | urgency"
}"""


def build_batch_prompt(batch: list[dict]) -> str:
    ads_text = ""
    for i, ad in enumerate(batch, 1):
        ads_text += (
            f"\n--- Ad {i} (id: {ad.get('ad_id', 'unknown')}) ---\n"
            f"Headline: {ad.get('ad_creative_link_title') or 'N/A'}\n"
            f"Body Copy: {ad.get('ad_creative_body') or 'N/A'}\n"
            f"Description: {ad.get('ad_creative_link_description') or 'N/A'}\n"
            f"CTA Type: {ad.get('cta_type') or 'N/A'}\n"
        )
    return (
        f"Analyze these {len(batch)} Health & Wellness ads and return a JSON array.\n"
        f"{ads_text}\n"
        f"Return ONLY a JSON array of exactly {len(batch)} objects, one per ad "
        f"in the same order, each matching this schema:\n{ANALYSIS_SCHEMA}"
    )


def analyze_batch(pool: GroqKeyPool, batch: list[dict]) -> list[dict]:
    prompt = build_batch_prompt(batch)
    pool.reset_rotation()

    while True:
        try:
            response = pool.client.chat.completions.create(
                model=TEXT_MODEL,
                max_tokens=2048,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            break
        except Exception as e:
            err = str(e)
            if GroqKeyPool.is_retriable(err):
                logger.warning("API error (%s) — trying next key…", err[:80])
                if not pool.rotate():
                    logger.error("All Groq API keys exhausted for this batch.")
                    return [{"ad_id": ad.get("ad_id"), "error": "all_keys_exhausted"} for ad in batch]
            else:
                raise

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if the model added them anyway
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        results = json.loads(raw)
        if not isinstance(results, list):
            results = [results]
        return results
    except json.JSONDecodeError as e:
        logger.error("JSON parse error in batch: %s\nRaw (first 400):\n%s", e, raw[:400])
        return [{"ad_id": ad.get("ad_id"), "error": "parse_failed"} for ad in batch]


def run(scored_path: str | Path, output_dir: str = "data/analyzed", force: bool = False) -> Path:
    scored_path = Path(scored_path)
    page_label = scored_path.stem.replace("_scored", "")
    output_path = Path(output_dir) / f"{page_label}_text_analysis.json"

    data = load_json(scored_path)
    ads = data.get("scored_ads", data) if isinstance(data, dict) else data

    # Load existing results and skip already-analyzed ad_ids (incremental)
    existing_results: list[dict] = []
    analyzed_ids: set[str] = set()
    if output_path.exists() and not force:
        existing_results = load_json(output_path)
        analyzed_ids = {r["ad_id"] for r in existing_results if r.get("ad_id") and not r.get("error")}

    new_ads = [a for a in ads if a.get("ad_id") not in analyzed_ids]

    if not new_ads:
        logger.info("Text analysis: all %d ads already analyzed — skipping. Use --force to rerun.", len(ads))
        return output_path

    logger.info(
        "Text analysis: %d new ads to analyze (%d already cached), batches of %d…",
        len(new_ads), len(analyzed_ids), BATCH_SIZE,
    )

    pool = GroqKeyPool()
    new_results: list[dict] = []
    total_batches = (len(new_ads) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, i in enumerate(range(0, len(new_ads), BATCH_SIZE), 1):
        batch = new_ads[i : i + BATCH_SIZE]
        logger.info("Text batch %d / %d (%d ads)…", batch_num, total_batches, len(batch))
        results = analyze_batch(pool, batch)
        new_results.extend(results)
        if batch_num < total_batches:
            time.sleep(INTER_BATCH_DELAY)

    all_results = existing_results + new_results
    save_json(all_results, output_path)
    logger.info("Saved text analysis (%d total, %d new) → %s", len(all_results), len(new_results), output_path)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Batch-analyze ad copy with Groq")
    parser.add_argument("--scored-file", required=True)
    parser.add_argument("--output-dir", default="data/analyzed")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run(args.scored_file, args.output_dir, args.force)
