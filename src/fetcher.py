"""
Scrape ads from the public Meta Ads Library using Playwright.

Strategy (in order of preference):
  1. Intercept internal GraphQL/AJAX network responses → clean structured JSON
  2. Extract embedded SSR JSON from <script> tags in the initial HTML
  3. DOM fallback for any remaining visible ad cards

Anti-detection: removes webdriver markers, uses realistic viewport/UA,
waits for human-like scroll pacing.

Usage:
    python src/fetcher.py --page "Carbamide Supplements" --country IN --max-ads 100
    python src/fetcher.py --page "Carbamide Supplements" --debug   # saves screenshot + HTML
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from playwright.sync_api import sync_playwright, Page, Response, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_logger, save_json, timestamp

logger = get_logger("fetcher")

ADS_LIBRARY_URL = "https://www.facebook.com/ads/library/"

SCROLL_PAUSE = 3.5
MAX_STALE_SCROLLS = 5
PAGE_LOAD_WAIT = 20          # seconds to let page + XHR settle before scrolling


# ── Stealth helpers ───────────────────────────────────────────────────────────

STEALTH_JS = """
() => {
    // Remove webdriver marker
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    // Fake plugins list
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    // Fake languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
    // Remove CDP markers
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
}
"""


# ── GraphQL / JSON response parser ────────────────────────────────────────────

def _parse_any_json_body(body: str) -> list[dict]:
    """
    Try every JSON object / NDJSON line in `body` looking for ad records.
    """
    ads: list[dict] = []
    if "ad_archive_id" not in body:
        return ads

    for line in body.strip().splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            data = json.loads(line)
            ads.extend(_walk_for_ads(data))
        except json.JSONDecodeError:
            pass

    return ads


def _walk_for_ads(obj, depth=0) -> list[dict]:
    if depth > 15 or not isinstance(obj, (dict, list)):
        return []

    if isinstance(obj, list):
        out = []
        for item in obj:
            out.extend(_walk_for_ads(item, depth + 1))
        return out

    # Direct ad unit — has both ad_archive_id and snapshot
    if "ad_archive_id" in obj and isinstance(obj.get("snapshot"), dict):
        ad = _normalize_unit(obj)
        return [ad] if ad else []

    # Collation wrappers — Meta uses both key names depending on context
    for wrapper_key in ("collated_results", "collationUnits"):
        if wrapper_key in obj:
            out = []
            for unit in obj.get(wrapper_key) or []:
                out.extend(_walk_for_ads(unit, depth + 1))
            return out

    out = []
    for v in obj.values():
        if isinstance(v, (dict, list)):
            out.extend(_walk_for_ads(v, depth + 1))
    return out


def _normalize_unit(unit: dict) -> dict | None:
    snap = unit.get("snapshot") or {}

    # Body text — Facebook stores this as a plain string in snapshot.body
    body_raw = snap.get("body")
    if isinstance(body_raw, dict):
        body_text = body_raw.get("text") or ""
    else:
        body_text = str(body_raw or "").strip()

    # Images from snapshot.images[]
    images: list[str] = []
    for img in snap.get("images") or []:
        url = img.get("original_image_url") or img.get("resized_image_url")
        if url:
            images.append(url)

    # Videos from snapshot.videos[] (if present) or snapshot.cards[].video_*
    videos: list[str] = []
    for vid in snap.get("videos") or []:
        url = (vid.get("video_hd_url")
               or vid.get("video_sd_url")
               or vid.get("video_preview_image_url"))
        if url:
            videos.append(url)

    # Carousel cards — each card may have its own image/video/copy
    cards: list[dict] = []
    for card in snap.get("cards") or []:
        card_img = card.get("original_image_url") or card.get("resized_image_url")
        card_vid = (card.get("video_hd_url")
                    or card.get("video_sd_url")
                    or card.get("video_preview_image_url"))
        if card_img and card_img not in images:
            images.append(card_img)
        if card_vid and card_vid not in videos:
            videos.append(card_vid)
        cards.append({
            "title": card.get("title"),
            "body": card.get("body"),
            "link_url": card.get("link_url"),
            "cta_type": card.get("cta_type"),
            "image_url": card_img,
            "video_url": card_vid,
        })

    # Dates — start_date / end_date are Unix timestamps at the UNIT level
    start_ts = unit.get("start_date")
    stop_ts = unit.get("end_date")
    start_str = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat() if start_ts else None
    stop_str = datetime.fromtimestamp(stop_ts, tz=timezone.utc).isoformat() if stop_ts else None

    # Spend — dict with lower_bound / upper_bound strings, at unit level
    spend = unit.get("spend") or {}
    # Impressions — stored as impressions_with_index at unit level
    imp = unit.get("impressions_with_index") or unit.get("impressions") or {}

    ad_id = str(unit.get("ad_archive_id") or "")
    if not ad_id:
        return None

    # page_name lives at BOTH unit level and snapshot level
    page_name = (unit.get("page_name") or snap.get("page_name") or "").strip()

    return {
        "ad_id": ad_id,
        "page_id": str(unit.get("page_id") or ""),
        "page_name": page_name,
        "page_profile_url": snap.get("page_profile_uri") or None,
        "ad_creative_body": body_text or None,
        "ad_creative_link_title": snap.get("title") or None,
        "ad_creative_link_description": snap.get("link_description") or None,
        "cta_type": snap.get("cta_type") or snap.get("cta_text") or None,
        "link_url": snap.get("link_url") or None,
        "display_format": snap.get("display_format") or None,
        "ad_delivery_start_time": start_str,
        "ad_delivery_stop_time": stop_str,
        "ad_snapshot_url": f"https://www.facebook.com/ads/library/?id={ad_id}",
        "ad_image_urls": images,
        "ad_video_urls": videos,
        "ad_cards": cards,
        "primary_image_url": images[0] if images else (videos[0] if videos else None),
        "currency": unit.get("currency") or None,
        "spend_lower": spend.get("lower_bound"),
        "spend_upper": spend.get("upper_bound"),
        "impressions_lower": imp.get("lower_bound"),
        "impressions_upper": imp.get("upper_bound"),
        "is_active": unit.get("is_active", True),
        "publisher_platforms": unit.get("publisher_platform") or [],
    }


# ── SSR extraction (embedded JSON in page HTML) ───────────────────────────────

def _extract_from_ssr(html: str) -> list[dict]:
    """
    Meta server-renders the initial ad batch as a JSON blob embedded inside the
    page HTML (inside require() calls). We find every occurrence of
    "collated_results":[  in the HTML, reconstruct the surrounding array,
    and parse each unit directly — no fragile regex needed for the outer structure.
    """
    if "collated_results" not in html and "ad_archive_id" not in html:
        return []

    ads: list[dict] = []
    seen: set[str] = set()

    # Scan for all "collated_results":[ occurrences and extract the array
    search_str = '"collated_results":['
    pos = 0
    while True:
        idx = html.find(search_str, pos)
        if idx == -1:
            break
        array_start = idx + len(search_str) - 1  # points to '['
        # Walk forward to find the matching ']'
        depth = 0
        array_end = array_start
        for i in range(array_start, min(array_start + 200_000, len(html))):
            c = html[i]
            if c == '[' or c == '{':
                depth += 1
            elif c == ']' or c == '}':
                depth -= 1
                if depth == 0:
                    array_end = i
                    break
        blob = html[array_start:array_end + 1]
        try:
            units = json.loads(blob)
            for unit in units if isinstance(units, list) else [units]:
                found = _walk_for_ads(unit)
                for ad in found:
                    if ad["ad_id"] not in seen:
                        seen.add(ad["ad_id"])
                        ads.append(ad)
        except (json.JSONDecodeError, Exception):
            pass
        pos = idx + 1

    if ads:
        logger.info("SSR extraction: found %d ads.", len(ads))
    return ads


# ── DOM fallback ──────────────────────────────────────────────────────────────

def _extract_from_dom(page: Page) -> list[dict]:
    """
    Last-resort DOM extraction. Looks for the ad archive IDs embedded as
    data attributes or in text, then extracts the surrounding card content.
    """
    return page.evaluate(r"""
    () => {
        const ads = [];
        // Meta embeds the archive ID in links like /ads/archive/render_ad/?id=XXXX
        const idPattern = /[?&]id=(\d+)/;

        // Find all ad container divs — they contain a "Library ID" text
        const allDivs = Array.from(document.querySelectorAll('div'));
        const cards = allDivs.filter(d => {
            const t = d.innerText || '';
            return t.includes('Library ID') && t.length > 50 && t.length < 5000;
        });

        // Deduplicate by archive id
        const seen = new Set();

        cards.forEach(card => {
            const text = card.innerText || '';

            // Extract Library ID
            const idMatch = text.match(/Library ID[:\s]+(\d+)/i);
            const ad_id = idMatch ? idMatch[1] : null;
            if (!ad_id || seen.has(ad_id)) return;
            seen.add(ad_id);

            // Extract start date
            const dateMatch = text.match(/[Ss]tarted running on[:\s]+([A-Za-z]+ \d{1,2},\s*\d{4})/);
            const start_date = dateMatch ? dateMatch[1] : null;

            // Extract page name — usually the first bold/strong or h2 inside the card
            const nameEl = card.querySelector('strong, h2, h3, [class*="x1heor9g"]');
            const page_name = nameEl ? nameEl.innerText.trim() : null;

            // Extract ad body — the longest span/div text that looks like copy
            const textEls = Array.from(card.querySelectorAll('span, p'))
                .filter(el => {
                    const t = el.innerText || '';
                    return el.children.length === 0 && t.length > 40
                        && !t.startsWith('Library ID')
                        && !t.startsWith('Started running');
                });
            textEls.sort((a, b) => b.innerText.length - a.innerText.length);
            const ad_creative_body = textEls[0] ? textEls[0].innerText.trim() : null;

            // Headline — second distinct text block
            const headline = textEls[1] ? textEls[1].innerText.trim().slice(0, 200) : null;

            // Image URLs
            const imgs = Array.from(card.querySelectorAll('img[src*="fbcdn"]'))
                .map(img => img.src)
                .filter(s => !s.includes('s60x60') && !s.includes('s32x32'));

            // Snapshot link
            const snapLink = card.querySelector('a[href*="render_ad"]');
            const snapshot_url = snapLink
                ? snapLink.href
                : (ad_id ? `https://www.facebook.com/ads/archive/render_ad/?id=${ad_id}` : null);

            // CTA button
            const ctaEl = Array.from(card.querySelectorAll('[role="button"]'))
                .find(b => b.innerText && b.innerText.length < 40
                    && !b.innerText.includes('Library ID'));
            const cta_type = ctaEl ? ctaEl.innerText.trim() : null;

            ads.push({
                ad_id,
                page_id: '',
                page_name: page_name || '',
                ad_creative_body,
                ad_creative_link_title: headline,
                ad_creative_link_description: null,
                cta_type,
                link_url: null,
                ad_delivery_start_time: start_date,
                ad_delivery_stop_time: null,
                ad_snapshot_url: snapshot_url,
                ad_image_urls: imgs,
                ad_video_urls: [],
                ad_cards: [],
                primary_image_url: imgs[0] || null,
                currency: null,
                spend_lower: null,
                spend_upper: null,
                impressions_lower: null,
                impressions_upper: null,
                is_active: true,
                _source: 'dom',
            });
        });

        return ads;
    }
    """)


# ── Main scraper ──────────────────────────────────────────────────────────────

def build_url(query: str, country: str = "ALL") -> str:
    params = {
        "active_status": "active",
        "ad_type": "all",
        "country": country,
        "q": query,
        "search_type": "page",
        "media_type": "image_and_meme",  # only fetch image/meme ads — no videos
    }
    return f"{ADS_LIBRARY_URL}?{urlencode(params)}"


def scrape_ads(
    query: str,
    country: str = "ALL",
    max_ads: int = 100,
    headless: bool = True,
    debug: bool = False,
) -> list[dict]:
    url = build_url(query, country)
    logger.info("Navigating to: %s", url)

    collected: list[dict] = []
    seen_ids: set[str] = set()
    intercepted_response_urls: list[str] = []   # for debug logging

    def merge(ads: list[dict]) -> None:
        for ad in ads:
            if ad.get("ad_id") and ad["ad_id"] not in seen_ids:
                seen_ids.add(ad["ad_id"])
                collected.append(ad)

    def on_response(response: Response) -> None:
        try:
            resp_url = response.url
            # Capture any Facebook API / AJAX response
            if "facebook.com" not in resp_url:
                return
            if response.status != 200:
                return

            # Broad filter — any internal API endpoint
            if not any(x in resp_url for x in [
                "/api/graphql", "api/graphql/", "/ajax/", "graphql?",
                "graph.facebook.com", "/ads/library/",
            ]):
                return

            intercepted_response_urls.append(resp_url)

            body = response.text()
            if "ad_archive_id" not in body:
                return

            logger.info("  [network] ad data in: %s", resp_url[:100])
            ads = _parse_any_json_body(body)
            if ads:
                before = len(collected)
                merge(ads)
                logger.info("  [network] +%d new ads (total %d)", len(collected) - before, len(collected))
        except Exception as exc:
            logger.debug("Response handler error: %s", exc)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # Remove webdriver/automation markers before any navigation
        page.add_init_script(STEALTH_JS)

        # Register response interceptor
        page.on("response", on_response)

        page.goto(url, wait_until="networkidle", timeout=45_000)

        # ── Consent dialogs ──
        for selector in [
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept all")',
            'button:has-text("Only allow essential cookies")',
            '[data-testid="cookie-policy-manage-dialog-accept-button"]',
            'button:has-text("Decline optional cookies")',
        ]:
            try:
                page.click(selector, timeout=3_000)
                logger.info("Dismissed consent dialog.")
                time.sleep(1)
                break
            except PWTimeout:
                continue

        # Let the page fully settle and fire its GraphQL requests
        logger.info("Waiting %ds for page to load ad data…", PAGE_LOAD_WAIT)
        time.sleep(PAGE_LOAD_WAIT)

        if debug:
            page.screenshot(path="debug_screenshot.png", full_page=False)
            Path("debug_page.html").write_text(page.content(), encoding="utf-8")
            logger.info("Debug: saved debug_screenshot.png and debug_page.html")
            logger.info("Debug: intercepted %d API URLs:", len(intercepted_response_urls))
            for u in intercepted_response_urls[:30]:
                logger.info("  %s", u)

        # ── SSR extraction from page HTML (catches initial batch) ──
        if len(collected) < 5:
            logger.info("Trying SSR extraction from page HTML…")
            ssr_ads = _extract_from_ssr(page.content())
            if ssr_ads:
                merge(ssr_ads)
                logger.info("SSR: found %d ads.", len(collected))

        # ── Scroll loop ──
        stale = 0
        last_count = len(collected)

        while len(collected) < max_ads:
            # Slow human-like scroll
            page.evaluate("""
                window.scrollBy({
                    top: window.innerHeight * 0.85,
                    behavior: 'smooth'
                })
            """)
            time.sleep(SCROLL_PAUSE)

            # Click load-more buttons if present
            for btn_text in ["See more results", "Load more ads", "Show more"]:
                try:
                    btn = page.query_selector(f'div[role="button"]:has-text("{btn_text}")')
                    if btn:
                        btn.scroll_into_view_if_needed()
                        btn.click()
                        time.sleep(SCROLL_PAUSE)
                        break
                except Exception:
                    pass

            # DOM fallback on every scroll — catches anything network missed
            dom_ads = _extract_from_dom(page)
            if dom_ads:
                merge(dom_ads)

            current = len(collected)
            if current == last_count:
                stale += 1
                logger.info("Scroll %d/%d — no new ads (total: %d)", stale, MAX_STALE_SCROLLS, current)
                if stale >= MAX_STALE_SCROLLS:
                    logger.info("Reached end of results.")
                    break
            else:
                stale = 0
                logger.info("Scroll — total ads now: %d", current)
                last_count = current

        browser.close()

    logger.info("Scrape complete. Unique ads collected: %d", len(collected))
    return collected[:max_ads]


# ── Image downloader ──────────────────────────────────────────────────────────

_IMG_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AdIntelBot/1.0)"}


def _download_images(ads: list[dict], img_dir: Path) -> list[dict]:
    """
    Download all ad images to img_dir and replace URLs with local file paths.
    Returns the updated ads list (mutates in place for efficiency).
    """
    img_dir.mkdir(parents=True, exist_ok=True)
    ext_map = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
    }

    def fetch(url: str, dest: Path) -> bool:
        if dest.exists():
            return True
        try:
            r = requests.get(url, headers=_IMG_HEADERS, timeout=15)
            r.raise_for_status()
            ct = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                return False
            # Re-add correct extension if needed
            suffix = ext_map.get(ct, ".jpg")
            if dest.suffix.lower() not in ext_map.values():
                dest = dest.with_suffix(suffix)
            dest.write_bytes(r.content)
            return True
        except Exception as e:
            logger.debug("Image download failed (%s): %s", url[:80], e)
            return False

    total, downloaded = 0, 0
    for ad in ads:
        ad_id = ad.get("ad_id", "unknown")
        local_paths: list[str] = []

        for i, url in enumerate(ad.get("ad_image_urls") or []):
            total += 1
            # Derive a safe filename from the URL
            url_path = url.split("?")[0].rstrip("/")
            original_name = url_path.split("/")[-1] or f"img_{i}"
            dest = img_dir / f"{ad_id}_{i}_{original_name[:60]}"
            if fetch(url, dest):
                # Find actual file (extension may have been corrected)
                actual = dest if dest.exists() else next(
                    (img_dir / f for f in img_dir.iterdir()
                     if f.name.startswith(f"{ad_id}_{i}_")), None
                )
                if actual and actual.exists():
                    local_paths.append(str(actual))
                    downloaded += 1
                    continue
            local_paths.append(url)  # keep original URL as fallback

        if local_paths:
            ad["ad_image_urls"] = local_paths
            ad["primary_image_url"] = local_paths[0] if local_paths else None

        # Update card image paths too
        for j, card in enumerate(ad.get("ad_cards") or []):
            if card.get("image_url"):
                dest = img_dir / f"{ad_id}_card{j}_{card['image_url'].split('/')[-1][:60].split('?')[0]}"
                if fetch(card["image_url"], dest) and dest.exists():
                    card["image_url"] = str(dest)

    logger.info("Images: downloaded %d / %d", downloaded, total)
    return ads


# ── Entry point ───────────────────────────────────────────────────────────────

def _make_page_label(ads: list[dict], page_query: str) -> str:
    label = (
        ads[0]["page_name"].strip().replace(" ", "_").lower()
        if ads and ads[0].get("page_name")
        else page_query.replace(" ", "_").lower()
    )
    return "".join(c if c.isalnum() or c == "_" else "_" for c in label)


def _make_label(custom: str | None, ads: list[dict], page_query: str) -> str:
    if custom and custom.strip():
        raw = custom.strip().lower().replace(" ", "_")
        return "".join(c if c.isalnum() or c == "_" else "_" for c in raw)
    return _make_page_label(ads, page_query)


def _filter_image_ads(ads: list[dict]) -> list[dict]:
    before = len(ads)
    ads = [
        a for a in ads
        if a.get("ad_image_urls")
        and not (a.get("ad_video_urls") and not a.get("ad_image_urls"))
    ]
    if len(ads) < before:
        logger.info("Filtered to image-only ads: %d → %d (removed %d video/empty)",
                    before, len(ads), before - len(ads))
    return ads


def _load_master(master_path: Path) -> tuple[list[dict], set[str]]:
    """Load master file and return (ads_list, known_ad_ids)."""
    if not master_path.exists():
        return [], set()
    try:
        data = json.loads(master_path.read_text(encoding="utf-8"))
        ads = data.get("ads", data) if isinstance(data, dict) else data
        return ads, {a["ad_id"] for a in ads if a.get("ad_id")}
    except Exception as e:
        logger.warning("Could not load master file (%s): %s", master_path, e)
        return [], set()


def _save_master(master_path: Path, ads: list[dict], page_query: str, country: str, page_label: str = "") -> None:
    master_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(
        {
            "page": page_query,
            "label": page_label or master_path.stem.replace("_master", ""),
            "country": country,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "total_ads": len(ads),
            "ads": ads,
        },
        master_path,
    )


def run(
    page_query: str,
    country: str = "ALL",
    max_ads: int = 100,
    output_dir: str = "data/raw",
    headless: bool = True,
    debug: bool = False,
    label: str | None = None,
) -> Path:
    ads = scrape_ads(page_query, country=country, max_ads=max_ads,
                     headless=headless, debug=debug)

    if not ads:
        raise RuntimeError(
            f"No ads found for '{page_query}'. "
            "Tips:\n"
            "  • Run with --no-headless to watch the browser\n"
            "  • Run with --debug to save a screenshot\n"
            "  • Try the exact page name from the Facebook Ads Library website\n"
            "  • Try --country ALL instead of a specific country"
        )

    page_label = _make_label(label, ads, page_query)
    ads = _filter_image_ads(ads)

    img_dir = Path(output_dir) / "images" / page_label
    logger.info("Downloading ad images to %s …", img_dir)
    ads = _download_images(ads, img_dir)

    filename = f"{page_label}_{timestamp()}.json"
    output_path = Path(output_dir) / filename

    payload = {
        "page": page_query,
        "label": page_label,
        "country": country,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_ads": len(ads),
        "ads": ads,
    }
    save_json(payload, output_path)
    logger.info("Saved %d ads → %s", len(ads), output_path)

    # Always keep master file up to date so the dashboard can load it
    master_dir = Path(output_dir) / "master"
    master_dir.mkdir(parents=True, exist_ok=True)
    master_path = master_dir / f"{page_label}_master.json"
    existing, existing_ids = _load_master(master_path)
    merged = existing + [a for a in ads if a.get("ad_id") not in existing_ids]
    _save_master(master_path, merged, page_query, country, page_label)
    logger.info("Master updated: %d total ads → %s", len(merged), master_path)

    # Auto-upload images to Supabase (new feature for Railway)
    try:
        logger.info("Auto-uploading images to Supabase…")
        from image_uploader import run as upload_run
        upload_run(str(master_path))
        logger.info("✓ Images auto-uploaded and master JSON updated with Supabase URLs")
    except Exception as e:
        logger.warning("Image auto-upload failed (non-blocking): %s", e)

    return output_path


def run_incremental(
    page_query: str,
    country: str = "ALL",
    new_ads_target: int = 50,
    output_dir: str = "data/raw",
    master_dir: str = "data/raw/master",
    headless: bool = True,
    debug: bool = False,
    label: str | None = None,
) -> tuple[Path, Path]:
    """
    Fetch only ads not already in the master file.

    Scrapes up to new_ads_target * 4 total ads, keeps only those whose
    ad_id is not in the existing master, stops once new_ads_target new
    ads have been collected or the page is exhausted.

    Returns (daily_snapshot_path, master_path).
    The daily snapshot contains NEW ads only.
    The master file is updated with all known ads (existing + new).
    """
    master_path = Path(master_dir)
    # Determine page_label from existing master or after first scrape
    # We'll try to find an existing master file
    existing_masters = list(master_path.glob("*_master.json")) if master_path.exists() else []
    page_label_guess = page_query.replace(" ", "_").lower()
    page_label_guess = "".join(c if c.isalnum() or c == "_" else "_" for c in page_label_guess)

    # Find matching master file
    matching_master = None
    for m in existing_masters:
        if m.stem.startswith(page_label_guess.split("_")[0]):
            matching_master = m
            break

    existing_ads, known_ids = _load_master(matching_master) if matching_master else ([], set())
    logger.info(
        "Incremental fetch — %d ads already in master, targeting %d new ads.",
        len(existing_ads), new_ads_target,
    )

    # Scrape more than we need — we'll filter to new ones
    fetch_max = max(new_ads_target * 4, 200)
    all_scraped = scrape_ads(page_query, country=country, max_ads=fetch_max,
                             headless=headless, debug=debug)

    if not all_scraped:
        raise RuntimeError(f"No ads found for '{page_query}'.")

    page_label = _make_label(label, all_scraped, page_query)
    all_scraped = _filter_image_ads(all_scraped)

    # Keep only truly new ads
    new_ads = [a for a in all_scraped if a.get("ad_id") and a["ad_id"] not in known_ids]
    new_ads = new_ads[:new_ads_target]

    logger.info(
        "Found %d new ads out of %d scraped (master had %d).",
        len(new_ads), len(all_scraped), len(existing_ads),
    )

    if new_ads:
        img_dir = Path(output_dir) / "images" / page_label
        logger.info("Downloading images for %d new ads → %s …", len(new_ads), img_dir)
        new_ads = _download_images(new_ads, img_dir)

    # Daily snapshot — new ads only
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_filename = f"{page_label}_{date_str}_new.json"
    daily_path = Path(output_dir) / daily_filename
    save_json(
        {
            "page": page_query,
            "label": page_label,
            "country": country,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch_type": "incremental",
            "new_ads_count": len(new_ads),
            "ads": new_ads,
        },
        daily_path,
    )
    logger.info("Daily snapshot saved (%d new ads) → %s", len(new_ads), daily_path)

    # Update master — merge existing + new (new ads appended at end)
    master_file = Path(master_dir) / f"{page_label}_master.json"
    merged_ads = existing_ads + new_ads
    _save_master(master_file, merged_ads, page_query, country, page_label)
    logger.info("Master updated (%d total ads) → %s", len(merged_ads), master_file)

    # Auto-upload images to Supabase (new feature for Railway)
    try:
        logger.info("Auto-uploading images to Supabase…")
        from image_uploader import run as upload_run
        upload_run(str(master_file))
        logger.info("✓ Images auto-uploaded and master JSON updated with Supabase URLs")
    except Exception as e:
        logger.warning("Image auto-upload failed (non-blocking): %s", e)

    return daily_path, master_file


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape Meta Ads Library")
    parser.add_argument("--page", required=True, help="Facebook Page name to search")
    parser.add_argument("--country", default="ALL", help="Country code: IN, US, GB, ALL")
    parser.add_argument("--max-ads", type=int, default=100)
    parser.add_argument("--label", default=None,
                        help="Custom label for all output files (e.g. berberine-jan). Defaults to page name.")
    parser.add_argument("--output-dir", default="data/raw")
    parser.add_argument("--master-dir", default="data/raw/master")
    parser.add_argument("--incremental", action="store_true",
                        help="Fetch only new ads not already in master file")
    parser.add_argument("--new-ads-target", type=int, default=50,
                        help="How many new ads to collect in incremental mode")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--debug", action="store_true",
                        help="Save debug_screenshot.png + debug_page.html")
    args = parser.parse_args()

    if args.incremental:
        run_incremental(
            args.page, args.country, args.new_ads_target,
            args.output_dir, args.master_dir,
            headless=not args.no_headless, debug=args.debug,
            label=args.label,
        )
    else:
        run(args.page, args.country, args.max_ads, args.output_dir,
            headless=not args.no_headless, debug=args.debug,
            label=args.label)
