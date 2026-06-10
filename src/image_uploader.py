"""
Upload local ad images to Supabase Storage and patch master JSON with Supabase URLs.

Usage:
  python src/image_uploader.py --master-file data/raw/master/plix_master.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_logger, load_json, save_json, upload_image

logger = get_logger("image_uploader")


def run(master_file: str | Path) -> None:
    master_file = Path(master_file)
    if not master_file.exists():
        raise FileNotFoundError(f"Master file not found: {master_file}")

    # Extract page label from filename (e.g., "plix_master.json" → "plix")
    page_label = master_file.stem.replace("_master", "")
    # master_file is at data/raw/master/plix_master.json
    # images are at data/raw/images/plix
    images_dir = master_file.parent.parent / "images" / page_label

    if not images_dir.exists():
        logger.warning(f"Images directory not found: {images_dir}")
        return

    # Load master JSON
    master_data = load_json(master_file)
    ads = master_data if isinstance(master_data, list) else master_data.get("ads", [])

    if not ads:
        logger.warning("No ads found in master JSON.")
        return

    logger.info(f"Processing {len(ads)} ads from {page_label}")

    uploaded_count = 0
    total_images = 0

    # Upload images and patch JSON
    for ad in ads:
        ad_id = ad.get("ad_id")
        if not ad_id:
            continue

        image_urls = []
        local_images = ad.get("ad_image_urls", [])

        for img_url in local_images:
            total_images += 1

            # Extract filename from URL (handles both URLs and Windows paths)
            if isinstance(img_url, str):
                # Try backslash first (Windows paths), then forward slash
                filename = img_url.replace("\\", "/").split("/")[-1]
                local_path = images_dir / filename

                if local_path.exists():
                    # Upload to Supabase
                    storage_key = f"images/{page_label}/{filename}"
                    supabase_url = upload_image(local_path, storage_key)

                    if supabase_url:
                        image_urls.append(supabase_url)
                        uploaded_count += 1
                        logger.info(f"[{uploaded_count}] Uploaded {filename} → {supabase_url[:60]}...")
                    else:
                        logger.warning(f"Failed to upload {filename}")
                        image_urls.append(img_url)  # Keep original if upload fails
                else:
                    logger.debug(f"Local file not found: {local_path} (tried: {img_url})")
                    image_urls.append(img_url)

        # Update JSON with Supabase URLs
        if image_urls:
            ad["ad_supabase_image_urls"] = image_urls

    # Save updated master JSON
    save_json(master_data, master_file)
    logger.info(f"✓ Uploaded {uploaded_count}/{total_images} images. Updated {master_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload ad images to Supabase and patch master JSON")
    parser.add_argument("--master-file", required=True, help="Path to master JSON file")
    args = parser.parse_args()
    run(args.master_file)
