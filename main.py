"""
Full pipeline CLI for Competitor Ad Intelligence.

Usage:
    python main.py --page "HimsHers" --fetch --score --analyze --dashboard
    python main.py --page "HimsHers" --score --analyze          # skip fetch, reuse latest raw
    python main.py --page "HimsHers" --analyze --force          # force re-analysis
    python main.py --page "HimsHers" --incremental --score --analyze  # fetch only new ads
"""

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "src"))
from utils import find_latest_file, get_logger

logger = get_logger("main")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Competitor Ad Intelligence — Health & Wellness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from scratch
  python main.py --page "HimsHers" --fetch --score --analyze --dashboard

  # Fetch only NEW ads (incremental), then re-analyze everything
  python main.py --page "HimsHers" --incremental --score --analyze

  # Re-analyze without re-fetching
  python main.py --page "HimsHers" --score --analyze

  # Force re-analysis (ignore cache)
  python main.py --page "HimsHers" --analyze --force

  # Open dashboard only
  python main.py --dashboard
        """,
    )
    parser.add_argument("--page", help="Facebook Page ID or page name to analyze")
    parser.add_argument("--fetch", action="store_true", help="Fetch ads from Meta Ads Library")
    parser.add_argument("--incremental", action="store_true",
                        help="Fetch only new ads not already in master file")
    parser.add_argument("--new-ads-target", type=int, default=50,
                        help="How many new ads to collect in incremental mode (default: 50)")
    parser.add_argument("--score", action="store_true", help="Score ads by run duration")
    parser.add_argument("--analyze", action="store_true", help="Run text + vision + aggregation analysis")
    parser.add_argument("--dashboard", action="store_true", help="Launch Streamlit dashboard")
    parser.add_argument("--force", action="store_true", help="Force re-analysis (ignore cache)")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--master-dir", default="data/raw/master")
    parser.add_argument("--scored-dir", default="data/scored")
    parser.add_argument("--analyzed-dir", default="data/analyzed")
    args = parser.parse_args()

    if not any([args.fetch, args.incremental, args.score, args.analyze, args.dashboard]):
        parser.print_help()
        sys.exit(0)

    raw_path: Path | None = None
    scored_path: Path | None = None
    page_label: str | None = None

    # ── Step 1a: Full Fetch ────────────────────────────────────────────────────
    if args.fetch:
        if not args.page:
            logger.error("--page is required when using --fetch")
            sys.exit(1)

        from fetcher import run as fetch_run

        logger.info("=== STEP 1: Fetching ads for '%s' ===", args.page)
        raw_path = fetch_run(args.page, args.raw_dir)

    # ── Step 1b: Incremental Fetch ─────────────────────────────────────────────
    if args.incremental:
        if not args.page:
            logger.error("--page is required when using --incremental")
            sys.exit(1)

        from fetcher import run_incremental as fetch_incremental

        logger.info("=== STEP 1 (INCREMENTAL): Fetching new ads for '%s' ===", args.page)
        daily_path, master_path = fetch_incremental(
            args.page,
            new_ads_target=args.new_ads_target,
            output_dir=args.raw_dir,
            master_dir=args.master_dir,
        )
        # Use the master file for downstream scoring so we score the full set
        raw_path = master_path
        logger.info("Incremental fetch done. Using master file for scoring: %s", master_path)

    # ── Step 2: Score ──────────────────────────────────────────────────────────
    if args.score:
        if raw_path is None:
            if args.page:
                safe_page = args.page.replace(" ", "_").lower()
                safe_page = "".join(c if c.isalnum() or c == "_" else "_" for c in safe_page)
                # Prefer master file if it exists (incremental workflow)
                raw_path = find_latest_file(args.master_dir, f"{safe_page}_master.json")
                if raw_path is None:
                    raw_path = find_latest_file(args.raw_dir, f"{safe_page}_*.json")
            if raw_path is None:
                raw_path = find_latest_file(args.raw_dir, "*.json")
            if raw_path is None:
                logger.error("No raw ads file found. Run --fetch first.")
                sys.exit(1)

        from scorer import run as score_run

        logger.info("=== STEP 2: Scoring ads from %s ===", raw_path)
        scored_path = score_run(raw_path, args.scored_dir)
        page_label = scored_path.stem.replace("_scored", "")

    # ── Step 3: Analyze ────────────────────────────────────────────────────────
    if args.analyze:
        if scored_path is None:
            if args.page:
                safe_page = args.page.replace(" ", "_").lower()
                scored_path = Path(args.scored_dir) / f"{safe_page}_scored.json"
            if scored_path is None or not scored_path.exists():
                scored_path = find_latest_file(args.scored_dir, "*.json")
            if scored_path is None:
                logger.error("No scored ads file found. Run --score first.")
                sys.exit(1)

        if page_label is None:
            page_label = scored_path.stem.replace("_scored", "")

        from text_analyzer import run as text_run
        from vision_analyzer import run as vision_run
        from aggregator import run as agg_run
        from visual_root_discoverer import run as visual_roots_run
        from root_discoverer import run as roots_run

        logger.info("=== STEP 3a: Text Analysis ===")
        text_run(scored_path, args.analyzed_dir, args.force)

        logger.info("=== STEP 3b: Vision Analysis (winners only) ===")
        vision_run(scored_path, args.analyzed_dir, args.force)

        logger.info("=== STEP 3c: Aggregating Themes ===")
        agg_run(page_label, args.analyzed_dir, args.force)

        logger.info("=== STEP 3d: Discovering Visual Format Roots ===")
        visual_roots_run(page_label, args.analyzed_dir, args.scored_dir, args.force)

        logger.info("=== STEP 3e: Discovering Creative Strategy Roots ===")
        roots_run(page_label, args.analyzed_dir, args.scored_dir, args.force)

    # ── Step 4: Dashboard ──────────────────────────────────────────────────────
    if args.dashboard:
        dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
        logger.info("=== Launching Streamlit dashboard ===")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
            check=True,
        )


if __name__ == "__main__":
    main()
