"""
Score and rank ads by: run_duration_days × creative_richness_multiplier.

Creative richness is derived purely from existing ad fields — no AI calls needed.
Ads with compelling copy, stats, and clear structure are boosted over plain image-only ads.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import find_latest_file, get_logger, load_json, save_json

logger = get_logger("scorer")

DATE_FORMATS = ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]

# Regex to detect numbers/stats in copy (e.g. "36%", "2x", "100mg", "6X")
_STATS_RE = re.compile(r'\d+\s*[%xX]|\d+\s*mg|\d+\s*times|\bno\.\s*\d', re.IGNORECASE)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    logger.warning("Could not parse date: %s", value)
    return None


def creative_richness(ad: dict) -> float:
    """
    Return a multiplier ≥ 1.0 based on how rich the ad creative is.
    Plain image with no copy → 1.0 (no boost)
    Full infographic with hook + stats + CTA → up to ~2.3x
    """
    multiplier = 1.0

    headline = (ad.get("ad_creative_link_title") or "").strip()
    body = (ad.get("ad_creative_body") or "").strip()
    cta = (ad.get("cta_type") or "").strip()
    cards = ad.get("ad_cards") or []

    # Has a proper headline
    if len(headline) > 5:
        multiplier *= 1.2

    # Has body copy with meaningful length
    if len(body) > 30:
        multiplier *= 1.2

    # Body contains stats/numbers (social proof like "36% reduction", "6X potent")
    combined_text = f"{headline} {body}"
    if _STATS_RE.search(combined_text):
        multiplier *= 1.3

    # Has a CTA type set
    if cta and cta.upper() not in ("", "UNKNOWN", "NO_BUTTON"):
        multiplier *= 1.1

    # Is a carousel (multiple cards = more creative effort, usually higher engagement)
    if len(cards) > 1:
        multiplier *= 1.1

    # Has both headline AND body (complete copy)
    if len(headline) > 5 and len(body) > 30:
        multiplier *= 1.1  # bonus for being fully complete

    return round(multiplier, 3)


def score_ads(ads: list[dict]) -> list[dict]:
    today = datetime.now(timezone.utc)
    composite_scores: list[float] = []

    for ad in ads:
        start = parse_date(ad.get("ad_delivery_start_time"))
        stop = parse_date(ad.get("ad_delivery_stop_time"))

        if start is None:
            ad["run_duration_days"] = None
            ad["richness_multiplier"] = 1.0
            ad["composite_score"] = 0.0
            continue

        end = stop if stop else today
        duration = max((end - start).days, 0)
        richness = creative_richness(ad)
        composite = round(duration * richness, 1)

        ad["run_duration_days"] = duration
        ad["richness_multiplier"] = richness
        ad["composite_score"] = composite
        composite_scores.append(composite)

    # Top 20% threshold based on composite score
    if composite_scores:
        scores_sorted = sorted(composite_scores)
        cutoff_index = max(0, int(len(scores_sorted) * 0.80) - 1)
        winner_threshold = scores_sorted[cutoff_index]
        logger.info(
            "Winner threshold: %.1f composite score (top 20%% of %d ads)",
            winner_threshold, len(composite_scores),
        )
    else:
        winner_threshold = 0

    for ad in ads:
        score = ad.get("composite_score", 0)
        ad["is_winner"] = score > 0 and score >= winner_threshold

    # Sort by composite score descending
    ads.sort(key=lambda a: a.get("composite_score") or 0, reverse=True)
    return ads


def run(raw_path: str | Path, output_dir: str = "data/scored") -> Path:
    raw_path = Path(raw_path)
    data = load_json(raw_path)
    ads = data.get("ads", data) if isinstance(data, dict) else data

    logger.info("Scoring %d ads from %s", len(ads), raw_path)
    scored = score_ads(ads)

    winners = sum(1 for a in scored if a.get("is_winner"))
    logger.info("Winners (top 20%% by composite score): %d / %d", winners, len(scored))

    # Log score breakdown for top 5
    for ad in scored[:5]:
        logger.info(
            "  [%s] duration=%s days × richness=%.2f → score=%.1f  winner=%s",
            ad.get("ad_id", "?"),
            ad.get("run_duration_days"),
            ad.get("richness_multiplier", 1.0),
            ad.get("composite_score", 0),
            ad.get("is_winner"),
        )

    # Use label stored in JSON if present (set by fetcher --label), else derive from filename
    if isinstance(data, dict) and data.get("label"):
        page_label = data["label"]
    else:
        stem = raw_path.stem
        if stem.endswith("_master"):
            page_label = stem[: -len("_master")]
        else:
            page_label = stem.rsplit("_", 2)[0]
    output_path = Path(output_dir) / f"{page_label}_scored.json"

    save_json(
        {"page": data.get("page", page_label) if isinstance(data, dict) else page_label,
         "scored_ads": scored},
        output_path,
    )
    logger.info("Saved scored ads to %s", output_path)
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Score ads by run duration × creative richness")
    parser.add_argument("--raw-file", help="Path to raw ads JSON")
    parser.add_argument("--raw-dir", default="data/raw", help="Auto-pick latest file from dir")
    parser.add_argument("--output-dir", default="data/scored")
    args = parser.parse_args()

    if args.raw_file:
        path = Path(args.raw_file)
    else:
        path = find_latest_file(args.raw_dir, "*.json")
        if not path:
            raise FileNotFoundError(f"No JSON files found in {args.raw_dir}")

    run(path, args.output_dir)
