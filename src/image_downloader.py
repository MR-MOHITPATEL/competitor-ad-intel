"""
Download (or re-download) images for an existing raw/scored JSON dataset.
Updates the JSON file in-place with local file paths.

Used when fetcher's image download failed, or data was fetched before the
local-download feature existed.
"""

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_logger, load_json, save_json

logger = get_logger("image_downloader")

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AdIntelBot/1.0)"}
_EXT_MAP = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
}


def _fetch_one(url: str, dest: Path, timeout: int = 20) -> Path | None:
    """Download url → dest. Returns actual saved path or None on failure."""
    if dest.exists():
        return dest
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not ct.startswith("image/"):
            return None
        suffix = _EXT_MAP.get(ct, ".jpg")
        if dest.suffix.lower() not in _EXT_MAP.values():
            dest = dest.with_suffix(suffix)
        dest.write_bytes(r.content)
        return dest
    except Exception as e:
        logger.debug("Download failed (%s): %s", str(url)[:80], e)
        return None


def download_for_ads(ads: list[dict], img_dir: Path) -> tuple[list[dict], int, int]:
    """
    For each ad, download any images that are still remote URLs.
    Returns (updated_ads, downloaded_count, total_count).
    """
    img_dir.mkdir(parents=True, exist_ok=True)
    total, downloaded = 0, 0

    for ad in ads:
        ad_id = ad.get("ad_id", "unknown")
        updated_urls: list[str] = []

        for i, url in enumerate(ad.get("ad_image_urls") or []):
            total += 1
            # Already a local path that exists — keep it
            local = Path(url)
            if local.exists():
                updated_urls.append(url)
                downloaded += 1
                continue

            # Remote URL — try to download
            url_path = url.split("?")[0].rstrip("/")
            fname = url_path.split("/")[-1] or f"img_{i}"
            dest = img_dir / f"{ad_id}_{i}_{fname[:60]}"
            saved = _fetch_one(url, dest)
            if saved:
                updated_urls.append(str(saved))
                downloaded += 1
            else:
                updated_urls.append(url)  # keep original as fallback

        ad["ad_image_urls"] = updated_urls
        ad["primary_image_url"] = updated_urls[0] if updated_urls else None

        # Card images
        for j, card in enumerate(ad.get("ad_cards") or []):
            card_url = card.get("image_url", "")
            if card_url and not Path(card_url).exists():
                fname = card_url.split("?")[0].split("/")[-1][:60]
                dest = img_dir / f"{ad_id}_card{j}_{fname}"
                saved = _fetch_one(card_url, dest)
                if saved:
                    card["image_url"] = str(saved)

    return ads, downloaded, total


def run(raw_path: str | Path, output_dir: str = "data/raw") -> tuple[int, int]:
    """
    Load raw JSON, download missing images, save updated JSON.
    Returns (downloaded, total) counts.
    """
    raw_path = Path(raw_path)
    data = load_json(raw_path)

    ads = data.get("ads", data) if isinstance(data, dict) else data

    # Derive page label — prefer filename stem (already sanitized by fetcher)
    page_label = raw_path.stem.split("_20")[0]  # strip _YYYYMMDD_HHMMSS timestamp
    if not page_label and isinstance(data, dict):
        page_name_raw = (ads[0].get("page_name", "") if ads else "") or data.get("page", "")
        page_label = page_name_raw.strip().replace(" ", "_").lower()
        page_label = "".join(c if c.isalnum() or c == "_" else "_" for c in page_label)

    img_dir = Path(output_dir) / "images" / page_label
    logger.info("Downloading images for %d ads → %s", len(ads), img_dir)

    ads, downloaded, total = download_for_ads(ads, img_dir)

    # Save updated JSON
    if isinstance(data, dict):
        data["ads"] = ads
        save_json(data, raw_path)
    else:
        save_json(ads, raw_path)

    logger.info("Images: %d / %d downloaded. Updated %s", downloaded, total, raw_path.name)
    return downloaded, total


def patch_scored(scored_path: str | Path, raw_path: str | Path) -> None:
    """
    Copy updated ad_image_urls / primary_image_url from raw into scored JSON.
    Run after download_for_ads has updated the raw file.
    """
    scored_path = Path(scored_path)
    raw_path = Path(raw_path)
    if not scored_path.exists():
        return

    raw_data = load_json(raw_path)
    raw_ads = raw_data.get("ads", raw_data) if isinstance(raw_data, dict) else raw_data
    url_map = {a["ad_id"]: a for a in raw_ads if a.get("ad_id")}

    scored_data = load_json(scored_path)
    scored_ads = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data

    for ad in scored_ads:
        ad_id = ad.get("ad_id")
        if ad_id in url_map:
            ad["ad_image_urls"] = url_map[ad_id].get("ad_image_urls", [])
            ad["primary_image_url"] = url_map[ad_id].get("primary_image_url")

    if isinstance(scored_data, dict):
        scored_data["scored_ads"] = scored_ads
        save_json(scored_data, scored_path)
    else:
        save_json(scored_ads, scored_path)

    logger.info("Patched scored JSON with local image paths → %s", scored_path.name)
