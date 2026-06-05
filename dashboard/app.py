"""
Competitor Ad Intelligence — Streamlit Dashboard (redesigned for non-tech users)
Run: streamlit run dashboard/app.py
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Path setup ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

DATA_RAW     = ROOT / "data" / "raw"
DATA_SCORED  = ROOT / "data" / "scored"
DATA_ANALYZED = ROOT / "data" / "analyzed"
DATA_MASTER  = ROOT / "data" / "raw" / "master"

# ── Page config — must be first Streamlit call ────────────────────────────────
st.set_page_config(
    page_title="Ad Intel — Competitor Research",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Ensure data dirs exist (important on first run / hosted server)
for _d in [DATA_RAW, DATA_SCORED, DATA_ANALYZED, DATA_MASTER]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Supabase sync (once per session on hosted server) ─────────────────────────
if "supabase_synced" not in st.session_state:
    try:
        from utils import sync_from_supabase
        _synced = sync_from_supabase(ROOT)
        if _synced:
            st.toast(f"☁️ Synced {_synced} file(s) from cloud storage", icon="✅")
    except Exception:
        pass
    st.session_state["supabase_synced"] = True

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Base typography ── */
  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* ── Hero banner ── */
  .hero-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 60%, #0f172a 100%);
    border-radius: 16px;
    padding: 32px 36px 28px;
    margin-bottom: 24px;
    border: 1px solid #1e3a5f;
  }
  .hero-title {
    font-size: 28px;
    font-weight: 800;
    color: #ffffff;
    margin: 0 0 6px 0;
    letter-spacing: -0.5px;
  }
  .hero-sub {
    font-size: 15px;
    color: #94a3b8;
    margin: 0;
  }

  /* ── Config card ── */
  .config-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }

  /* step badge pill (used inline in markdown) */
  .step-badge {
    background: #dcfce7; color: #166534;
    padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
  }

  /* ── Stat pill ── */
  .stat-pill {
    display: inline-flex; align-items: center; gap: 6px;
    background: #f1f5f9; border: 1px solid #e2e8f0;
    padding: 6px 14px; border-radius: 20px;
    font-size: 13px; color: #334155; font-weight: 500;
    margin-right: 8px; margin-bottom: 8px;
  }
  .stat-pill strong { color: #0f172a; font-size: 15px; }

  /* ── Insight card ── */
  .insight-card {
    background: #1e2433; border: 1px solid #374151;
    border-radius: 12px; padding: 18px 20px;
    color: #f3f4f6; margin-bottom: 12px;
  }
  .insight-card .card-title {
    font-size: 15px; font-weight: 700; color: #fff; margin-bottom: 6px;
  }
  .insight-card .card-body { font-size: 14px; line-height: 1.6; color: #d1d5db; }

  /* ── Winner card ── */
  .winner-badge {
    background: #fef3c7; color: #92400e;
    padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
  }

  /* ── Root pill ── */
  .root-pill {
    display: inline-block;
    background: #1e3a2f; color: #6ee7b7;
    padding: 2px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 500;
    margin-bottom: 4px;
  }

  /* ── Banner variants ── */
  .banner-blue {
    background: #1e3a5f; border-left: 4px solid #3b82f6;
    padding: 14px 18px; border-radius: 8px; color: #e0f2fe;
    margin-bottom: 16px;
  }
  .banner-green {
    background: #1a2e1a; border-left: 4px solid #22c55e;
    padding: 14px 18px; border-radius: 8px; color: #d1fae5;
    margin-bottom: 16px;
  }
  .banner-amber {
    background: #2d2a1e; border-left: 4px solid #f59e0b;
    padding: 14px 18px; border-radius: 8px; color: #fef3c7;
    margin-bottom: 16px;
  }

  /* ── Generated ad box ── */
  .ad-box {
    background: #1e2433; border: 1px solid #374151;
    border-radius: 12px; padding: 20px;
    color: #f3f4f6;
  }
  .ad-headline { font-size: 20px; font-weight: 800; color: #fff; margin-bottom: 10px; }
  .ad-body     { font-size: 14px; line-height: 1.7; margin-bottom: 14px; color: #d1d5db; }
  .ad-cta {
    display: inline-block; background: #2563eb; color: #fff;
    padding: 8px 20px; border-radius: 8px; font-weight: 700; font-size: 14px;
  }

  /* ── Hide Streamlit chrome ── */
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
  div[data-testid="stExpander"] { border: 1px solid #e5e7eb !important; border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)


# ── Session state ──────────────────────────────────────────────────────────────
defaults = {
    "raw_path": None,
    "scored_path": None,
    "page_label": None,
    "step_done": {i: False for i in range(1, 8)},
    "step_counts": {},
    "last_page": "",
    "run_all": False,
    "run_all_step": 1,
    "last_generated_ad": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helpers ────────────────────────────────────────────────────────────────────
def resolve_image(url: str) -> str:
    """Return a displayable image source.
    Local path → use as-is if it exists.
    Local path that doesn't exist → return empty string (skip).
    Remote URL → return as-is (works on hosted server).
    """
    if not url:
        return ""
    if str(url).startswith("http://") or str(url).startswith("https://"):
        return url
    p = Path(url)
    return str(p) if p.exists() else ""

def get_display_images(ad: dict) -> list[str]:
    """Get displayable image URLs — prefers permanent Supabase URLs, then local, then CDN."""
    supabase_urls = ad.get("ad_supabase_image_urls") or []
    local_urls = ad.get("ad_image_urls") or []
    remote_urls = ad.get("ad_remote_image_urls") or []

    # Supabase URLs are permanent — always prefer them
    if supabase_urls:
        return [u for u in supabase_urls if u]

    result = []
    for url in local_urls:
        src = resolve_image(url)
        if src:
            result.append(src)

    # If no local images resolved, use remote CDN URLs as last resort
    if not result:
        result = [u for u in remote_urls if u]

    return result

def load_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def find_latest(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None

def step_state(n: int) -> str:
    if st.session_state.step_done.get(n):
        return "done"
    if n == 1 or st.session_state.step_done.get(n - 1):
        return "active"
    return "locked"

def step_enabled(n: int) -> bool:
    return n == 1 or bool(st.session_state.step_done.get(n - 1))

def mark_done(n: int, count_label: str = ""):
    st.session_state.step_done[n] = True
    if count_label:
        st.session_state.step_counts[n] = count_label


# ── HERO ───────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-banner">
  <p class="hero-title">🔍 Competitor Ad Intelligence</p>
  <p class="hero-sub">Discover what ads your competitors are running — and what's actually working for them</p>
</div>
""", unsafe_allow_html=True)


# ── CONFIG ─────────────────────────────────────────────────────────────────────
with st.container():
    col_name, col_country, col_btn = st.columns([5, 1, 2])

    with col_name:
        page_name = st.text_input(
            "Competitor's Facebook Page Name",
            value=st.session_state.last_page,
            placeholder="e.g.  Carbamide Forte   ·   Hims   ·   WOW Skin Science",
            label_visibility="visible",
        )
    with col_country:
        country = st.selectbox(
            "Country",
            ["IN", "US", "GB", "ALL", "AU", "CA", "SG", "AE"],
            index=0,
        )
    with col_btn:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        run_all_clicked = st.button(
            "🚀  Analyze Everything",
            disabled=not page_name,
            use_container_width=True,
            type="primary",
            help="Automatically run all 7 steps in order",
        )

    # ── Fetch New Ads (secondary action) ───────────────────────────────────────
    fc1, fc2, fc3 = st.columns([2, 1, 5])
    with fc1:
        new_ads_target_cfg = st.number_input(
            "New ads to fetch (incremental)",
            min_value=10, max_value=200, value=50, step=10,
        )
    with fc2:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        fetch_new_clicked = st.button(
            "🔄 Fetch New Ads",
            disabled=not page_name,
            use_container_width=True,
            help="Fetch only ads not already in your library, then re-analyze",
        )

    # ── Advanced settings (defaults — overridden inside expander) ─────────────
    batch_label = ""
    max_ads = 100
    force = False

    # ── Advanced settings ──────────────────────────────────────────────────────
    with st.expander("⚙️ Advanced Settings", expanded=False):
        ax1, ax2, ax3, ax4 = st.columns([2, 1, 1, 1])
        with ax1:
            batch_label = st.text_input(
                "📁 File Label",
                value="",
                placeholder="e.g. berberine-jan  (leave blank = auto)",
                help="All output files will use this prefix. Same label on next fetch updates existing files.",
            )
            if batch_label.strip() or page_name:
                _pl = batch_label.strip().lower().replace(" ", "_") if batch_label.strip() else (
                    "".join(c if c.isalnum() or c == "_" else "_"
                            for c in page_name.replace(" ", "_").lower()) if page_name else "your_label"
                )
                st.caption(f"Files: `{_pl}_scored.json`, `{_pl}_vision_analysis.json`, `{_pl}_roots.json`")
        with ax2:
            max_ads = st.number_input("Max Ads", min_value=10, max_value=500, value=100, step=10)
        with ax3:
            force = st.checkbox(
                "Force re-analyze",
                value=False,
                help="Re-run all analysis even if results already exist",
            )
        with ax4:
            st.markdown("")

# Reset state when page changes
if page_name and page_name != st.session_state.last_page:
    st.session_state.step_done = {i: False for i in range(1, 8)}
    st.session_state.step_counts = {}
    st.session_state.raw_path = None
    st.session_state.scored_path = None
    st.session_state.page_label = None
    st.session_state.last_page = page_name

# Activate Run All
if run_all_clicked and page_name:
    st.session_state.run_all = True
    st.session_state.run_all_step = 1

# ── Master library status ──────────────────────────────────────────────────────
if DATA_MASTER.exists():
    master_files = sorted(DATA_MASTER.glob("*_master.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if master_files:
        try:
            _md = load_json(master_files[0])
            _ma = _md.get("ads", [])
            _mu = _md.get("last_updated", "")[:10]
            st.caption(f"📚 Saved library: **{len(_ma)} total ads** · last updated {_mu} · `{master_files[0].name}`")
        except Exception:
            pass

st.divider()


# ── INCREMENTAL FETCH ──────────────────────────────────────────────────────────
if fetch_new_clicked and page_name:
    with st.status("🔄 Fetching new ads…", expanded=True) as _inc_status:
        try:
            st.write(f"Searching **{page_name}** for ads not yet in your library…")
            cmd = [
                sys.executable, "-u", str(SRC / "fetcher.py"),
                "--page", page_name, "--country", country,
                "--incremental", "--new-ads-target", str(int(new_ads_target_cfg)),
                "--output-dir", str(DATA_RAW), "--master-dir", str(DATA_MASTER),
            ]
            if batch_label.strip():
                cmd += ["--label", batch_label.strip()]
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            result = subprocess.run(cmd, capture_output=True, cwd=str(ROOT), env=child_env)
            log_output = (
                result.stdout.decode("utf-8", errors="replace")
                + result.stderr.decode("utf-8", errors="replace")
            )
            if log_output.strip():
                with st.expander("📋 Fetch log", expanded=False):
                    st.code(log_output[-3000:], language=None)

            new_masters = sorted(DATA_MASTER.glob("*_master.json"),
                                 key=lambda p: p.stat().st_mtime, reverse=True)
            if not new_masters:
                raise RuntimeError("No master file found after fetch.")

            master_data = load_json(new_masters[0])
            master_ads = master_data.get("ads", [])

            import datetime as _dt
            date_str = _dt.date.today().isoformat()
            daily_files = sorted(DATA_RAW.glob(f"*{date_str}_new.json"),
                                 key=lambda p: p.stat().st_mtime, reverse=True)
            new_count = int(new_ads_target_cfg)
            if daily_files:
                _dd = load_json(daily_files[0])
                new_count = _dd.get("new_ads_count", len(_dd.get("ads", [])))

            st.write(f"✅ **{new_count} new ads** added · Library now has **{len(master_ads)} total**")
            st.session_state.raw_path = new_masters[0]
            st.session_state.step_done[1] = True
            st.session_state.step_done[2] = False
            st.session_state.step_counts[1] = f"{len(master_ads)} ads"
            _inc_status.update(
                label=f"✅ +{new_count} new ads · {len(master_ads)} total in library",
                state="complete",
            )
        except Exception as _e:
            _inc_status.update(label=f"❌ Fetch failed: {_e}", state="error")
            st.error(str(_e))
    st.rerun()


# ── PIPELINE STEPS UI ──────────────────────────────────────────────────────────
STEPS = [
    ("Fetch Ads",            "Collect ads from Meta Ads Library for this competitor",     "🌐"),
    ("Score & Rank",         "Find which ads ran the longest — those are the winners",     "📊"),
    ("Read Ad Copy",         "Understand the messaging: hooks, promises, tone",            "📝"),
    ("Analyze Images",       "AI reads every ad image — layout, colors, visual structure", "🖼️"),
    ("Find Themes",          "Discover the big strategic patterns across all ads",         "🎯"),
    ("Visual Format Types",  "Group ads by how they look — briefs for your designer",      "🖼️"),
    ("Layout Structures",    "Group ads by pure spatial layout — structural blueprints",   "📐"),
]

left_col, right_col = st.columns([3, 2])

with left_col:
    st.markdown("### Pipeline")
    if st.session_state.run_all and not all(st.session_state.step_done.values()):
        st.info("⚡ Running all steps automatically…")

    run_step = [False] * 7
    for i, (label, desc, emoji) in enumerate(STEPS):
        n = i + 1
        state = step_state(n)
        done  = st.session_state.step_done.get(n)
        count = st.session_state.step_counts.get(n, "")
        needs_page = (n == 1) and not page_name
        enabled    = step_enabled(n) and not needs_page

        icon = "✅" if done else ("🔵" if state == "active" else "⚪")
        label_md = f"**{icon} {n}. {emoji} {label}**"
        if count:
            label_md += f"  `{count}`"
        caption_color = "#6b7280" if state == "locked" else "#374151"

        scol1, scol2 = st.columns([6, 1])
        with scol1:
            st.markdown(label_md)
            st.caption(desc)
        with scol2:
            run_step[i] = st.button(
                "Run" if not done else "↺",
                key=f"step_btn_{n}",
                disabled=not enabled,
                use_container_width=True,
                type="primary" if (enabled and not done) else "secondary",
                help=f"Run: {label}",
            )
        st.markdown("<div style='margin-bottom:4px'></div>", unsafe_allow_html=True)

        # Auto-trigger in Run All mode
        if st.session_state.run_all and not done and enabled and not needs_page:
            run_step[i] = True

    if not page_name:
        st.info("👆 Enter a competitor page name above to get started.")

with right_col:
    # ── Upload master JSON (for hosted server — fetch runs locally) ────────────
    with st.expander("☁️ Upload Ads File (from your local machine)", expanded=not DATA_MASTER.exists() or not any(DATA_MASTER.glob("*_master.json"))):
        st.caption("Fetch ads locally → upload the master JSON here → run Steps 2–7 on the server.")
        uploaded_file = st.file_uploader(
            "Drop your master JSON file here",
            type=["json"],
            help="After fetching ads locally, upload the *_master.json file from data/raw/master/",
        )
        if uploaded_file is not None:
            try:
                raw_bytes = uploaded_file.read()
                uploaded_data = json.loads(raw_bytes)
                ads_in_file = uploaded_data.get("ads", [])
                file_label = uploaded_data.get("label", uploaded_file.name.replace("_master.json", "").replace(".json", ""))

                if not ads_in_file:
                    st.error("This file has no ads. Make sure you upload a *_master.json file.")
                else:
                    st.write(f"**{len(ads_in_file)} ads** found · label: `{file_label}`")
                    if st.button("✅ Save & Use This File", key="save_upload", type="primary"):
                        DATA_MASTER.mkdir(parents=True, exist_ok=True)
                        save_path = DATA_MASTER / f"{file_label}_master.json"
                        from utils import save_json as _save_json
                        _save_json(uploaded_data, save_path)  # writes local + uploads to Supabase
                        st.session_state.raw_path = save_path
                        st.session_state.step_done[1] = True
                        st.session_state.step_done[2] = False
                        st.session_state.step_counts[1] = f"{len(ads_in_file)} ads"
                        st.session_state.last_page = uploaded_data.get("page", file_label)
                        st.success(f"✅ Saved {len(ads_in_file)} ads — run Step 2 to score them.")
                        st.rerun()
            except Exception as _ue:
                st.error(f"Could not read file: {_ue}")

    # ── Resume from file ───────────────────────────────────────────────────────
    with st.expander("📂 Load from saved data", expanded=True):
        st.caption("Pick a competitor to work with — all data is loaded automatically.")
        master_files = sorted(DATA_MASTER.glob("*_master.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        scored_files = sorted(DATA_SCORED.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        if master_files:
            selected_master = st.selectbox(
                "Select competitor",
                options=[None] + [p.name for p in master_files],
                format_func=lambda x: "— select —" if x is None else x.replace("_master.json", "").replace("_", " ").title(),
                key="resume_master",
            )
            if selected_master and st.button("✅ Load", key="use_master"):
                chosen = DATA_MASTER / selected_master
                data = load_json(chosen)
                ads = data.get("ads", data) if isinstance(data, dict) else data
                label = chosen.stem.replace("_master", "")
                st.session_state.raw_path = chosen
                st.session_state.page_label = label
                st.session_state.step_done[1] = True
                st.session_state.step_counts[1] = f"{len(ads)} ads"

                # Build Supabase URL map from master so visual roots can show images
                _supabase_url_map = {
                    a.get("ad_id"): (
                        a.get("ad_supabase_image_urls")
                        or a.get("ad_remote_image_urls")
                        or a.get("ad_image_urls", [])
                    )
                    for a in ads if a.get("ad_id")
                }

                # Auto-load any existing scored/analyzed files for this competitor
                scored_p = DATA_SCORED / f"{label}_scored.json"
                if scored_p.exists():
                    sc_data = load_json(scored_p)
                    sc_ads = sc_data.get("scored_ads", [])
                    winners = sum(1 for a in sc_ads if a.get("is_winner"))
                    # Also enrich supabase URL map from scored file
                    for a in sc_ads:
                        aid = a.get("ad_id")
                        if aid and not _supabase_url_map.get(aid):
                            _supabase_url_map[aid] = (
                                a.get("ad_supabase_image_urls")
                                or a.get("ad_remote_image_urls")
                                or a.get("ad_image_urls", [])
                            )
                    st.session_state.scored_path = scored_p
                    st.session_state.step_done[2] = True
                    st.session_state.step_counts[2] = f"{winners} winners"

                for step_n, fname, key in [
                    (3, f"{label}_text_analysis.json",    "text"),
                    (4, f"{label}_vision_analysis.json",  "vision"),
                    (5, f"{label}_aggregated_themes.json","themes"),
                    (6, f"{label}_visual_roots.json",     "vroots"),
                    (7, f"{label}_layout_roots.json",     "layouts"),
                ]:
                    p = DATA_ANALYZED / fname
                    if p.exists():
                        d = load_json(p)
                        _dget = d.get if isinstance(d, dict) else {}.get

                        # Patch visual/strategy roots: replace local paths with Supabase URLs
                        if key in ("vroots", "roots") and isinstance(d, dict):
                            root_key = "visual_roots" if key == "vroots" else "roots"
                            for root in d.get(root_key, []):
                                patched = []
                                for item in root.get("ad_images", []):
                                    aid = item.get("ad_id", "")
                                    img = item.get("image_url", "")
                                    # Replace local Windows path with Supabase URL
                                    if img and (img.startswith("C:\\") or img.startswith("/") or not img.startswith("http")):
                                        urls = _supabase_url_map.get(aid, [])
                                        img = urls[0] if urls else ""
                                    patched.append({"ad_id": aid, "image_url": img})
                                root["ad_images"] = patched
                            # Save patched file back so future loads are instant
                            from utils import save_json as _save_json
                            _save_json(d, p)

                        counts = {
                            "text":    f"{len(d)} analyzed",
                            "vision":  f"{len(d)} images",
                            "themes":  f"{len(_dget('top_themes', d if isinstance(d, list) else []))} themes",
                            "vroots":  f"{len(_dget('visual_roots', d if isinstance(d, list) else []))} visual roots",
                            "layouts": f"{len(_dget('layout_roots', d if isinstance(d, list) else []))} layouts",
                        }
                        st.session_state.step_done[step_n] = True
                        st.session_state.step_counts[step_n] = counts[key]

                st.success(f"Loaded {len(ads)} ads for {label.replace('_',' ').title()}!")
                st.rerun()
        else:
            st.info("No competitor data found yet. Ask your team to upload a master file.")

st.divider()

# ── Download images (outside expander to avoid nesting error) ─────────────────
if st.session_state.step_done.get(1):
    _raw_for_dl = st.session_state.get("raw_path")
    if _raw_for_dl is None:
        _rf = sorted(DATA_RAW.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        _raw_for_dl = _rf[0] if _rf else None
    if _raw_for_dl:
        _raw_for_dl = Path(_raw_for_dl)
        _dl_stem = _raw_for_dl.stem.split("_20")[0]
        _img_folder = DATA_RAW / "images" / _dl_stem
        _img_count = sum(1 for _ in _img_folder.glob("*.*")) if _img_folder.exists() else 0
        _di1, _di2 = st.columns([4, 1])
        with _di1:
            if _img_count == 0:
                st.warning(f"⚠️ No local images for `{_dl_stem}` — download them for vision analysis.")
            else:
                st.info(f"🖼️ {_img_count} images saved locally for `{_dl_stem}`.")
        with _di2:
            if st.button("📥 Download Ad Images", key="dl_images"):
                with st.status("Downloading images…", expanded=True) as _dl_status:
                    try:
                        from image_downloader import run as dl_run, patch_scored
                        _dl, _total = dl_run(_raw_for_dl, str(DATA_RAW))
                        st.write(f"✅ Downloaded **{_dl} / {_total}** images")
                        _scored_cands = sorted(
                            DATA_SCORED.glob(f"{_dl_stem}*scored*.json"),
                            key=lambda p: p.stat().st_mtime, reverse=True,
                        )
                        if _scored_cands:
                            patch_scored(_scored_cands[0], _raw_for_dl)
                        _dl_status.update(label=f"✅ {_dl}/{_total} images downloaded", state="complete")
                        st.rerun()
                    except Exception as _e:
                        _dl_status.update(label=f"❌ Download failed: {_e}", state="error")


# ─────────────────────────────────────────────────────────────────────────────
# STEP EXECUTION BLOCKS
# ─────────────────────────────────────────────────────────────────────────────

# ── Step 1: Fetch ──────────────────────────────────────────────────────────────
if run_step[0]:
    with st.status("🌐 Fetching ads from Meta Ads Library…", expanded=True) as status:
        try:
            st.write(f"Searching for **{page_name}** · country: **{country}** · up to **{max_ads} ads**")
            st.write("_(Browser is running in the background — takes 30–60 seconds)_")
            cmd = [
                sys.executable, "-u", str(SRC / "fetcher.py"),
                "--page", page_name, "--country", country,
                "--max-ads", str(int(max_ads)), "--output-dir", str(DATA_RAW),
            ]
            if batch_label.strip():
                cmd += ["--label", batch_label.strip()]
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            result = subprocess.run(cmd, capture_output=True, cwd=str(ROOT), env=child_env)
            log_output = (
                result.stdout.decode("utf-8", errors="replace")
                + result.stderr.decode("utf-8", errors="replace")
            )
            if log_output.strip():
                with st.expander("📋 Log", expanded=False):
                    st.code(log_output[-3000:], language=None)

            raw_path = find_latest(DATA_RAW, "*.json")
            if raw_path is None:
                raise RuntimeError(
                    f"No output file saved (exit code {result.returncode}).\nLog:\n{log_output[-800:]}"
                )
            if result.returncode != 0:
                st.warning("⚠️ Fetcher exited with a warning but data was saved.")

            data = load_json(raw_path)
            ads = data.get("ads", [])
            st.write(f"✅ **{len(ads)} ads** collected successfully.")
            st.session_state.raw_path = raw_path
            mark_done(1, f"{len(ads)} ads")
            status.update(label=f"✅ Fetched {len(ads)} ads", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Fetch failed", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 2: Score ──────────────────────────────────────────────────────────────
if run_step[1]:
    raw_path = st.session_state.raw_path
    if raw_path is None:
        safe = "".join(c if c.isalnum() or c == "_" else "_"
                       for c in page_name.replace(" ", "_").lower())
        raw_path = find_latest(DATA_RAW, f"{safe}_*.json") or find_latest(DATA_RAW, "*.json")

    with st.status("📊 Ranking ads by performance…", expanded=True) as status:
        try:
            from scorer import run as score_run
            data = load_json(raw_path)
            n_ads = len(data.get("ads", []))
            st.write(f"Scoring **{n_ads} ads** — calculating how long each ad ran and how rich the creative is…")
            scored_path = score_run(raw_path, str(DATA_SCORED))
            scored_data = load_json(scored_path)
            scored_ads = scored_data.get("scored_ads", [])
            winners = sum(1 for a in scored_ads if a.get("is_winner"))
            st.write(f"✅ **{winners} winner ads** identified (top 20% by run duration)")
            st.session_state.scored_path = scored_path
            st.session_state.page_label = scored_path.stem.replace("_scored", "")
            mark_done(2, f"{winners} winners")
            status.update(label=f"✅ {winners} winner ads found", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Scoring failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 3: Text Analysis ──────────────────────────────────────────────────────
if run_step[2]:
    scored_path = st.session_state.scored_path
    if scored_path is None:
        safe = "".join(c if c.isalnum() or c == "_" else "_"
                       for c in page_name.replace(" ", "_").lower())
        scored_path = DATA_SCORED / f"{safe}_scored.json"
        if not scored_path.exists():
            scored_path = find_latest(DATA_SCORED, "*.json")

    with st.status("📝 Reading ad copy…", expanded=True) as status:
        try:
            scored_data = load_json(scored_path)
            ads = scored_data.get("scored_ads", [])
            st.write(f"Analyzing **{len(ads)} ads** — hooks, promises, emotional tone, CTA style…")
            cmd = [
                sys.executable, "-u", str(SRC / "text_analyzer.py"),
                "--scored-file", str(scored_path), "--output-dir", str(DATA_ANALYZED),
            ] + (["--force"] if force else [])
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

            progress_bar = st.progress(0.0)
            status_text = st.empty()
            log_lines: list[str] = []

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=child_env, text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                log_lines.append(line)
                m = re.search(r'Text batch (\d+) / (\d+)', line)
                if m:
                    cur, tot = int(m.group(1)), int(m.group(2))
                    progress_bar.progress(cur / tot)
                    status_text.text(f"Reading batch {cur} of {tot}…")
            proc.wait()
            progress_bar.progress(1.0)

            if log_lines:
                with st.expander("📋 Log", expanded=False):
                    st.code("\n".join(log_lines[-60:]), language=None)

            page_label = scored_path.stem.replace("_scored", "")
            out_path = DATA_ANALYZED / f"{page_label}_text_analysis.json"
            if not out_path.exists():
                raise RuntimeError(f"Output not found: {out_path}")
            results = load_json(out_path)
            analyzed = [r for r in results if not r.get("error")]
            status_text.empty()
            st.write(f"✅ **{len(analyzed)} ads** analyzed")
            st.session_state.page_label = page_label
            mark_done(3, f"{len(analyzed)} analyzed")
            status.update(label=f"✅ Ad copy analyzed — {len(analyzed)} ads", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 4: Vision Analysis ────────────────────────────────────────────────────
if run_step[3]:
    scored_path = st.session_state.scored_path
    if scored_path is None:
        safe = "".join(c if c.isalnum() or c == "_" else "_"
                       for c in page_name.replace(" ", "_").lower())
        scored_path = DATA_SCORED / f"{safe}_scored.json"
        if not scored_path.exists():
            scored_path = find_latest(DATA_SCORED, "*.json")

    with st.status("🖼️ Analyzing ad images…", expanded=True) as status:
        try:
            scored_data = load_json(scored_path)
            ads = scored_data.get("scored_ads", [])
            image_ads = [a for a in ads if a.get("ad_image_urls") or a.get("primary_image_url")]
            st.write(f"**{len(image_ads)} images** to analyze — AI reads layout, colors, visual structure…")
            st.write("_(~4 seconds per image via Gemini Vision AI)_")
            cmd = [
                sys.executable, "-u", str(SRC / "vision_analyzer.py"),
                "--scored-file", str(scored_path), "--output-dir", str(DATA_ANALYZED),
            ] + (["--force"] if force else [])
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

            progress_bar = st.progress(0.0)
            status_text = st.empty()
            log_lines: list[str] = []
            total_images = max(1, len(image_ads))

            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=child_env, text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                line = line.rstrip()
                log_lines.append(line)
                m = re.search(r'Vision (\d+) / (\d+)', line)
                if m:
                    cur, tot = int(m.group(1)), int(m.group(2))
                    total_images = tot
                    progress_bar.progress(cur / tot)
                    status_text.text(f"Analyzing image {cur} of {tot}…")
            proc.wait()
            progress_bar.progress(1.0)

            if log_lines:
                with st.expander("📋 Log", expanded=False):
                    st.code("\n".join(log_lines[-80:]), language=None)

            page_label = scored_path.stem.replace("_scored", "")
            out_path = DATA_ANALYZED / f"{page_label}_vision_analysis.json"
            if not out_path.exists():
                raise RuntimeError(f"Output not found: {out_path}")
            results = load_json(out_path)
            analyzed = [r for r in results if not r.get("error")]
            status_text.empty()
            st.write(f"✅ **{len(analyzed)} images** analyzed")
            st.session_state.page_label = page_label
            mark_done(4, f"{len(analyzed)} images")
            status.update(label=f"✅ Images analyzed — {len(analyzed)} ads", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 5: Aggregate Themes ───────────────────────────────────────────────────
if run_step[4]:
    page_label = st.session_state.page_label
    if not page_label:
        page_label = "".join(c if c.isalnum() or c == "_" else "_"
                             for c in page_name.replace(" ", "_").lower())

    with st.status("🎯 Finding strategic patterns…", expanded=True) as status:
        try:
            from aggregator import run as agg_run
            text_path   = DATA_ANALYZED / f"{page_label}_text_analysis.json"
            vision_path = DATA_ANALYZED / f"{page_label}_vision_analysis.json"
            text_ads    = load_json(text_path)   if text_path.exists()   else []
            vision_ads  = load_json(vision_path) if vision_path.exists() else []
            st.write(f"Merging **{len(text_ads)} copy analyses** + **{len(vision_ads)} image analyses**…")
            st.write("Making one AI call to surface the big themes…")
            out_path = agg_run(page_label, str(DATA_ANALYZED), force=force)
            themes = load_json(out_path)
            n_themes = len(themes.get("top_themes", []))
            st.write(f"✅ **{n_themes} themes** discovered")
            mark_done(5, f"{n_themes} themes")
            status.update(label=f"✅ {n_themes} strategic themes found", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 6: Visual Format Roots ────────────────────────────────────────────────
if run_step[5]:
    page_label = st.session_state.page_label
    if not page_label:
        page_label = "".join(c if c.isalnum() or c == "_" else "_"
                             for c in page_name.replace(" ", "_").lower())

    with st.status("🖼️ Grouping ads by visual format…", expanded=True) as status:
        try:
            vision_path = DATA_ANALYZED / f"{page_label}_vision_analysis.json"
            vision_ads  = load_json(vision_path) if vision_path.exists() else []
            valid = [a for a in vision_ads if not a.get("error") and a.get("visual_format")]
            st.write(f"Clustering **{len(valid)} ads** by layout + content type…")
            cmd = [
                sys.executable, "-u", str(SRC / "visual_root_discoverer.py"),
                "--page-label", page_label,
                "--analyzed-dir", str(DATA_ANALYZED), "--scored-dir", str(DATA_SCORED),
            ] + (["--force"] if force else [])
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            spinner_text = st.empty()
            spinner_text.text("⏳ AI is grouping ads by visual format…")
            log_lines: list[str] = []
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=child_env, text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                log_lines.append(line.rstrip())
            proc.wait()
            spinner_text.empty()
            if log_lines:
                with st.expander("📋 Log", expanded=False):
                    st.code("\n".join(log_lines[-40:]), language=None)
            out_path = DATA_ANALYZED / f"{page_label}_visual_roots.json"
            if not out_path.exists():
                raise RuntimeError(f"Output not found: {out_path}")
            vroots_data = load_json(out_path)
            n_vroots = len(vroots_data.get("visual_roots", []))
            st.write(f"✅ **{n_vroots} visual format types** discovered")
            mark_done(6, f"{n_vroots} visual types")
            status.update(label=f"✅ {n_vroots} visual format types found", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ── Step 7: Layout Structure Roots ────────────────────────────────────────────
if run_step[6]:
    page_label = st.session_state.page_label
    if not page_label:
        page_label = "".join(c if c.isalnum() or c == "_" else "_"
                             for c in page_name.replace(" ", "_").lower())

    with st.status("📐 Finding layout structure roots…", expanded=True) as status:
        try:
            vision_path = DATA_ANALYZED / f"{page_label}_vision_analysis.json"
            vision_ads  = load_json(vision_path) if vision_path.exists() else []
            valid = [a for a in vision_ads if not a.get("error") and a.get("visual_format")]
            st.write(f"Clustering **{len(valid)} ads** by pure spatial layout structure…")
            cmd = [
                sys.executable, "-u", str(SRC / "layout_discoverer.py"),
                "--page-label", page_label,
                "--analyzed-dir", str(DATA_ANALYZED), "--scored-dir", str(DATA_SCORED),
            ] + (["--force"] if force else [])
            child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            spinner_text = st.empty()
            spinner_text.text("⏳ AI is finding layout structure blueprints…")
            log_lines: list[str] = []
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=str(ROOT), env=child_env, text=True, encoding="utf-8", errors="replace",
            )
            for line in proc.stdout:
                log_lines.append(line.rstrip())
            proc.wait()
            spinner_text.empty()
            if log_lines:
                with st.expander("📋 Log", expanded=False):
                    st.code("\n".join(log_lines[-40:]), language=None)
            out_path = DATA_ANALYZED / f"{page_label}_layout_roots.json"
            if not out_path.exists():
                raise RuntimeError(f"Output not found: {out_path}")
            layout_data = load_json(out_path)
            n_layouts = len(layout_data.get("layout_roots", []))
            st.write(f"✅ **{n_layouts} layout structures** discovered")
            st.session_state.run_all = False
            mark_done(7, f"{n_layouts} layouts")
            status.update(label=f"✅ {n_layouts} layout structure roots found", state="complete")
        except Exception as e:
            st.session_state.run_all = False
            status.update(label=f"❌ Failed: {e}", state="error")
            st.error(str(e))
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# RESULTS
# ─────────────────────────────────────────────────────────────────────────────
page_label = st.session_state.page_label
if not page_label and page_name:
    safe = "".join(c if c.isalnum() or c == "_" else "_"
                   for c in page_name.replace(" ", "_").lower())
    page_label = safe if (DATA_ANALYZED / f"{safe}_text_analysis.json").exists() else None

if not page_label:
    existing = [p.stem.replace("_text_analysis", "")
                for p in DATA_ANALYZED.glob("*_text_analysis.json")]
    if existing:
        page_label = sorted(existing)[-1]

themes_data = None
merged = []

if page_label and (DATA_ANALYZED / f"{page_label}_text_analysis.json").exists():

    # Load all data
    text_path         = DATA_ANALYZED / f"{page_label}_text_analysis.json"
    vision_path       = DATA_ANALYZED / f"{page_label}_vision_analysis.json"
    themes_path       = DATA_ANALYZED / f"{page_label}_aggregated_themes.json"
    layout_roots_path = DATA_ANALYZED / f"{page_label}_layout_roots.json"
    visual_roots_path = DATA_ANALYZED / f"{page_label}_visual_roots.json"
    scored_path       = DATA_SCORED / f"{page_label}_scored.json"
    if not scored_path.exists():
        scored_path = find_latest(DATA_SCORED, "*.json")

    text_data          = load_json(text_path)          if text_path.exists()         else []
    vision_data        = load_json(vision_path)        if vision_path.exists()        else []
    themes_data        = load_json(themes_path)        if themes_path.exists()        else {}
    layout_roots_data  = load_json(layout_roots_path)  if layout_roots_path.exists()  else {}
    visual_roots_data_loaded = load_json(visual_roots_path) if visual_roots_path.exists() else {}
    scored_data        = load_json(scored_path)        if scored_path and scored_path.exists() else {}
    scored_ads         = scored_data.get("scored_ads", scored_data) if isinstance(scored_data, dict) else scored_data

    text_map   = {a.get("ad_id"): a for a in text_data  if a.get("ad_id")}
    vision_map = {a.get("ad_id"): a for a in vision_data if a.get("ad_id")}
    scored_map = {a.get("ad_id"): a for a in scored_ads  if a.get("ad_id")}

    ad_layout_map: dict[str, dict] = {}
    for root in layout_roots_data.get("layout_roots", []):
        for aid in root.get("ad_ids", []):
            ad_layout_map[aid] = root

    all_ids = set(text_map) | set(scored_map)
    for aid in all_ids:
        row = {**(scored_map.get(aid) or {}), **(text_map.get(aid) or {})}
        if aid in vision_map:
            row["_visual"] = vision_map[aid]
        if aid in ad_layout_map:
            row["_root"] = ad_layout_map[aid]
        merged.append(row)
    merged.sort(key=lambda a: a.get("run_duration_days") or 0, reverse=True)
    winners = [a for a in merged if a.get("is_winner")]

    # ── Stats bar ──────────────────────────────────────────────────────────────
    title = page_label.replace("_", " ").title()
    st.subheader(f"📈 Results — {title}")

    stats_html = ""
    stats_html += f'<span class="stat-pill">🗂️ <strong>{len(merged)}</strong> total ads</span>'
    stats_html += f'<span class="stat-pill">🏆 <strong>{len(winners)}</strong> winner ads</span>'
    avg_days = round(sum(a.get("run_duration_days") or 0 for a in merged) / max(len(merged), 1), 1)
    stats_html += f'<span class="stat-pill">📅 avg <strong>{avg_days}</strong> days running</span>'
    if themes_data:
        n_th = len(themes_data.get("top_themes", []))
        stats_html += f'<span class="stat-pill">🎯 <strong>{n_th}</strong> themes</span>'
    if visual_roots_data_loaded:
        n_vr = len(visual_roots_data_loaded.get("visual_roots", []))
        stats_html += f'<span class="stat-pill">🖼️ <strong>{n_vr}</strong> visual types</span>'
    if layout_roots_data:
        n_lr = len(layout_roots_data.get("layout_roots", []))
        stats_html += f'<span class="stat-pill">📐 <strong>{n_lr}</strong> layout structures</span>'
    st.markdown(stats_html, unsafe_allow_html=True)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🎯 Themes & Insights",
        "📋 All Ads",
        "🏆 Winners",
        "🖼️ Visual Format Types",
        "📐 Layout Structures",
    ])

    # ── Tab 1: Themes ──────────────────────────────────────────────────────────
    with tab1:
        if not themes_data:
            st.info("Run Step 5 (Find Themes) to see strategic insights here.")
        else:
            root_msg = themes_data.get("root_message", "")
            if root_msg:
                st.markdown(
                    f'<div class="banner-amber"><strong>💡 Their Core Message:</strong><br>{root_msg}</div>',
                    unsafe_allow_html=True,
                )

            th1, th2 = st.columns(2)
            th1.metric("Dominant Emotional Angle", themes_data.get("dominant_emotional_angle", "—"))
            th2.metric("Most Used Hook Style",     themes_data.get("most_used_hook", "—"))

            underused = themes_data.get("underused_angles", [])
            if underused:
                st.markdown(
                    '<div class="banner-green"><strong>💡 Opportunity Gaps — angles competitors aren\'t using:</strong><br>'
                    + "  ·  ".join(underused) + "</div>",
                    unsafe_allow_html=True,
                )

            top_themes = themes_data.get("top_themes", [])
            if top_themes:
                st.markdown(f"#### 🎯 {len(top_themes)} Dominant Themes")
                cols = st.columns(min(len(top_themes), 3))
                for i, theme in enumerate(top_themes):
                    with cols[i % 3]:
                        freq = theme.get("frequency", "?")
                        st.markdown(
                            f"""<div class="insight-card">
                            <div class="card-title">{theme.get('theme_name','')}</div>
                            <div class="card-body">{theme.get('description', '')}</div>
                            <div style="margin-top:10px;font-size:12px;color:#6b7280;">{freq} ads use this theme</div>
                            </div>""",
                            unsafe_allow_html=True,
                        )

    # ── Tab 2: All Ads ─────────────────────────────────────────────────────────
    with tab2:
        if not merged:
            st.info("Run Steps 1–3 to see ads here.")
        else:
            fc1, fc2, fc3 = st.columns([2, 2, 1])
            with fc1:
                hook_filter = st.multiselect(
                    "Filter by Hook Type",
                    options=sorted(set(a.get("hook_type", "") for a in merged if a.get("hook_type"))),
                )
            with fc2:
                tone_filter = st.multiselect(
                    "Filter by Emotional Tone",
                    options=sorted(set(a.get("emotional_tone", "") for a in merged if a.get("emotional_tone"))),
                )
            with fc3:
                winners_only = st.checkbox("Winners only")

            filtered = merged
            if hook_filter:  filtered = [a for a in filtered if a.get("hook_type") in hook_filter]
            if tone_filter:  filtered = [a for a in filtered if a.get("emotional_tone") in tone_filter]
            if winners_only: filtered = [a for a in filtered if a.get("is_winner")]

            st.caption(f"Showing {len(filtered)} of {len(merged)} ads")

            rows = []
            for ad in filtered:
                _r = ad.get("_root") or {}
                rows.append({
                    "Ad ID":      ad.get("ad_id", ""),
                    "Strategy":   f"{_r.get('root_emoji','')}{_r.get('root_name','—')}" if _r else "—",
                    "Hook":       ad.get("hook_type", "—"),
                    "Tone":       ad.get("emotional_tone", "—"),
                    "CTA":        ad.get("cta_style", "—"),
                    "Their Claim": (ad.get("core_claim") or "")[:90],
                    "Days Running": ad.get("run_duration_days") or None,
                    "Winner":     "🏆" if ad.get("is_winner") else "",
                })
            if rows:
                df = pd.DataFrame(rows)
                st.dataframe(df, use_container_width=True, hide_index=True,
                             column_config={
                                 "Their Claim": st.column_config.TextColumn(width="large"),
                                 "Days Running": st.column_config.NumberColumn(format="%d d"),
                             })

            st.markdown("---")
            st.markdown("**🔎 View Full Ad Detail**")
            ad_ids = [a.get("ad_id") for a in filtered if a.get("ad_id")]
            if ad_ids:
                chosen_id = st.selectbox("Select Ad ID", ad_ids, key="detail_select")
                chosen = next((a for a in filtered if a.get("ad_id") == chosen_id), None)
                if chosen:
                    dc1, dc2 = st.columns(2)
                    with dc1:
                        st.markdown("**Ad Copy**")
                        st.markdown(f"**Headline:** {chosen.get('ad_creative_link_title') or '—'}")
                        st.markdown(f"**Body:** {(chosen.get('ad_creative_body') or '—')[:400]}")
                        st.markdown(f"**CTA:** {chosen.get('cta_type') or '—'}")
                        ad_lib_url = f"https://www.facebook.com/ads/library/?id={chosen.get('ad_id','')}"
                        st.markdown(f"[🔗 View on Facebook Ad Library]({ad_lib_url})")
                    with dc2:
                        st.markdown("**AI Analysis**")
                        st.markdown(f"**Hook:** `{chosen.get('hook_type', '—')}`")
                        st.markdown(f"**Tone:** `{chosen.get('emotional_tone', '—')}`")
                        st.markdown(f"**Core Claim:** {chosen.get('core_claim', '—')}")
                        st.markdown(f"**Target Audience:** {chosen.get('target_audience_signal', '—')}")
                        st.markdown(f"**Days Running:** {chosen.get('run_duration_days', '—')}")
                        imgs = get_display_images(chosen)
                        if imgs:
                            img_cols = st.columns(min(len(imgs), 3))
                            for ci, img_url in enumerate(imgs[:3]):
                                with img_cols[ci]:
                                    try:
                                        st.image(img_url, use_container_width=True)
                                    except Exception:
                                        st.markdown(f"[Image {ci+1}]({img_url})")

    # ── Tab 3: Winners ─────────────────────────────────────────────────────────
    with tab3:
        if not winners:
            st.info("No winner ads found. Run Steps 1–4 to see winners here.")
        else:
            st.markdown(
                f'<div class="banner-blue">🏆 <strong>{len(winners)} winning ads</strong> — '
                "these ran the longest, meaning they were profitable enough to keep running.</div>",
                unsafe_allow_html=True,
            )

            for ad in winners:
                ad_id  = ad.get("ad_id", "")
                days   = ad.get("run_duration_days", "?")
                hook   = ad.get("hook_type", "—")
                tone   = ad.get("emotional_tone", "—")
                score  = ad.get("composite_score", "")
                _wr    = ad.get("_root") or {}
                root_tag = f"  ·  {_wr.get('root_emoji','')}{_wr.get('root_name','')}" if _wr else ""
                title_text = (ad.get("ad_creative_link_title") or "")[:50]
                score_label = f"  ·  {days} days  ·  score {score}" if score else f"  ·  {days} days"

                with st.expander(
                    f"🏆 {title_text or ad_id}{score_label}  ·  {hook}  ·  {tone}{root_tag}",
                    expanded=False,
                ):
                    wc1, wc2, wc3 = st.columns([2, 2, 2])
                    with wc1:
                        st.markdown("**📝 Ad Copy**")
                        if ad.get("ad_creative_link_title"):
                            st.markdown(f"**Headline:** {ad['ad_creative_link_title']}")
                        st.markdown(f"**Body:** {(ad.get('ad_creative_body') or '—')[:300]}")
                        st.markdown(f"**CTA:** {ad.get('cta_type', '—')}")
                        ad_lib_url = f"https://www.facebook.com/ads/library/?id={ad.get('ad_id','')}"
                        st.markdown(f"[🔗 View on Facebook Ad Library]({ad_lib_url})")
                    with wc2:
                        st.markdown("**🧠 What makes it work**")
                        st.markdown(f"**Hook:** `{ad.get('hook_type', '—')}`")
                        st.markdown(f"**Emotional Tone:** `{ad.get('emotional_tone', '—')}`")
                        st.markdown(f"**Their Claim:** {ad.get('core_claim', '—')}")
                        st.markdown(f"**Targets:** {ad.get('target_audience_signal', '—')}")
                        st.markdown(f"**Ran for:** {days} days")
                    with wc3:
                        visual = ad.get("_visual")
                        if visual and not visual.get("error"):
                            st.markdown("**👁️ Visual Style**")
                            st.markdown(f"**Format:** `{visual.get('visual_format', '—')}`")
                            story = visual.get("story_arc", "")
                            if story:
                                st.markdown(f"**Story:** {story}")
                            st.markdown(f"**Colors:** {visual.get('color_palette', '—')}")
                        else:
                            st.info("Run Step 4 to see image analysis.")

                    imgs = get_display_images(ad)
                    if imgs:
                        st.markdown("**Ad Images**")
                        img_cols = st.columns(min(len(imgs), 4))
                        for ci, img_url in enumerate(imgs[:4]):
                            with img_cols[ci]:
                                try:
                                    st.image(img_url, use_container_width=True)
                                except Exception:
                                    st.markdown(f"[Image {ci+1}]({img_url})")

    # ── Tab 4: Visual Format Types ─────────────────────────────────────────────
    with tab4:
        if not visual_roots_data_loaded:
            st.info("Run Step 6 (Visual Format Types) to see how competitors design their ads.")
        else:
            vroots_list       = visual_roots_data_loaded.get("visual_roots", [])
            dominant_vroot_id = visual_roots_data_loaded.get("dominant_visual_root", "")
            saturated         = visual_roots_data_loaded.get("saturated_formats", [])
            underused_formats = visual_roots_data_loaded.get("underused_formats", [])
            vsummary          = visual_roots_data_loaded.get("summary", "")

            if vsummary:
                st.markdown(
                    f'<div class="banner-blue"><strong>🖼️ Visual Summary</strong><br>{vsummary}</div>',
                    unsafe_allow_html=True,
                )
            if saturated:
                st.warning(f"⚠️ **Overused formats** (competitors over-rely on these): {', '.join(saturated)}")
            if underused_formats:
                st.success(f"💡 **Unused formats** (your creative white space): {'  ·  '.join(underused_formats)}")

            st.markdown(f"#### 🖼️ {len(vroots_list)} Visual Format Types")

            for vroot in vroots_list:
                vrid        = vroot.get("root_id", "")
                is_dominant = vrid == dominant_vroot_id
                emoji       = vroot.get("root_emoji", "🖼️")
                name        = vroot.get("root_name", vrid)
                ad_count    = vroot.get("ad_count") or len(vroot.get("ad_ids", []))
                desc        = vroot.get("description", "")
                sat_signal  = vroot.get("saturation_signal", "")
                sat_color   = {"dominant": "🔴", "common": "🟡", "occasional": "🟢", "rare": "🔵"}.get(sat_signal, "⚪")
                dominant_tag = " 👑 Most Used" if is_dominant else ""

                with st.expander(
                    f"{emoji} **{name}**  ·  {ad_count} ads  ·  {sat_color} {sat_signal}{dominant_tag}",
                    expanded=is_dominant,
                ):
                    st.markdown(f"_{desc}_")
                    vt    = vroot.get("visual_template", {})
                    brief = vroot.get("designer_brief", "")

                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown("**📐 Layout**")
                        st.markdown(f"- **Structure:** `{vt.get('layout_structure', vroot.get('layout_structure','—'))}`")
                        st.markdown(f"- **Content:** `{vt.get('content_type', vroot.get('content_type','—'))}`")
                        st.markdown(f"- **Color Mood:** {vt.get('color_mood', vroot.get('color_mood','—'))}`")
                    with c2:
                        st.markdown("**📊 How Saturated?**")
                        st.markdown(f"- **{ad_count} ads** use this format")
                        if vrid in saturated:
                            st.warning("Overused — differentiate your version.")
                        else:
                            st.success("Has room for differentiation.")

                    if brief:
                        st.markdown("**🎨 Designer Brief**")
                        st.info(brief)

                    ad_images = vroot.get("ad_images", [])
                    if ad_images:
                        st.markdown(f"**Sample Ads ({len(ad_images)} with images)**")
                        gallery_cols = st.columns(min(len(ad_images), 4))
                        for gi, item in enumerate(ad_images[:8]):
                            img_url = item.get("image_url", "")
                            aid = item.get("ad_id", "")
                            with gallery_cols[gi % 4]:
                                if img_url:
                                    try:
                                        src = resolve_image(img_url) or img_url
                                        st.image(src, use_container_width=True, caption=aid[:20])
                                    except Exception:
                                        st.markdown(f"[{aid[:15]}]")
                    elif vroot.get("ad_ids"):
                        st.caption(f"Ad IDs: {', '.join(vroot['ad_ids'][:5])}" +
                                   (" …" if len(vroot['ad_ids']) > 5 else ""))

    # ── Tab 5: Layout Structures ───────────────────────────────────────────────
    with tab5:
        if not layout_roots_data:
            st.info("Run Step 7 (Layout Structures) to see the spatial blueprints competitors use.")
        else:
            layout_list      = layout_roots_data.get("layout_roots", [])
            dominant_layout  = layout_roots_data.get("dominant_layout", "")
            underused_layouts = layout_roots_data.get("underused_layouts", [])
            summary          = layout_roots_data.get("summary", "")

            if summary:
                st.markdown(
                    f'<div class="banner-blue"><strong>📐 Layout Summary</strong><br>{summary}</div>',
                    unsafe_allow_html=True,
                )
            if underused_layouts:
                st.success(f"💡 **Untapped layouts**: {'  ·  '.join(underused_layouts)}")

            st.markdown(f"#### 📐 {len(layout_list)} Layout Structure Roots")

            for layout in layout_list:
                lid          = layout.get("layout_id", "")
                is_dominant  = lid == dominant_layout
                emoji        = layout.get("layout_emoji", "📐")
                name         = layout.get("layout_name", lid)
                ad_count     = layout.get("ad_count") or len(layout.get("ad_ids", []))
                desc         = layout.get("description", "")
                dominant_tag = " 👑 Most Used" if is_dominant else ""
                sat          = layout.get("saturation_signal", "")
                sat_tag      = {"dominant": " 🔴 dominant", "common": " 🟡 common",
                                "occasional": " 🟢 occasional", "rare": " 🔵 rare"}.get(sat, "")

                with st.expander(
                    f"{emoji} **{name}**  ·  {ad_count} ads{dominant_tag}{sat_tag}",
                    expanded=is_dominant
                ):
                    st.markdown(f"_{desc}_")

                    lc1, lc2 = st.columns(2)
                    with lc1:
                        st.markdown("**🗺️ Spatial Structure**")
                        st.markdown(f"- **Zones:** `{layout.get('zones','—')}`")
                        skeleton = layout.get("skeleton", "")
                        if skeleton:
                            st.caption(skeleton)
                    with lc2:
                        st.markdown("**🔄 Flexibility**")
                        flexibility = layout.get("flexibility", "")
                        if flexibility:
                            st.markdown(flexibility)

                    brief = layout.get("structure_brief", "")
                    if brief:
                        st.markdown("**📋 Designer Spatial Blueprint**")
                        st.info(brief)

                    ad_images = layout.get("ad_images", [])
                    if ad_images:
                        st.markdown(f"**Sample Ads ({len(ad_images)} with images)**")
                        gallery_cols = st.columns(min(len(ad_images), 4))
                        for gi, item in enumerate(ad_images[:8]):
                            img_url = item.get("image_url", "")
                            aid = item.get("ad_id", "")
                            with gallery_cols[gi % 4]:
                                if img_url:
                                    try:
                                        src = resolve_image(img_url) or img_url
                                        st.image(src, use_container_width=True, caption=aid[:20])
                                    except Exception:
                                        st.markdown(f"[{aid[:15]}]")
                    elif layout.get("ad_ids"):
                        st.caption(f"Ad IDs: {', '.join(layout['ad_ids'][:5])}" +
                                   (" …" if len(layout['ad_ids']) > 5 else ""))

else:
    if page_name and any(st.session_state.step_done.values()):
        st.info("Complete at least Steps 1–3 to see results here.")
    elif page_name:
        existing = [p.stem.replace("_text_analysis", "")
                    for p in DATA_ANALYZED.glob("*_text_analysis.json")]
        if existing:
            st.markdown("#### 📂 Previously Analyzed Competitors")
            st.caption("Load one of these to view their results.")
            for lbl in sorted(existing):
                st.markdown(f"- `{lbl}`")


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE MY AD
# ─────────────────────────────────────────────────────────────────────────────
_has_analysis = themes_data is not None or (
    DATA_ANALYZED.exists() and any(DATA_ANALYZED.glob("*_text_analysis.json"))
)

if _has_analysis:
    st.divider()
    st.subheader("✨ Generate My Ad")
    st.caption("Enter your product details — we'll write an ad inspired by what's working for competitors.")

    g1, g2, g3 = st.columns([2, 2, 2])
    with g1:
        my_product  = st.text_input("Your Product Name",  placeholder="e.g. ZenJeevani Ashwagandha")
    with g2:
        my_benefit  = st.text_input("Key Benefit",        placeholder="e.g. Reduces stress, improves sleep")
    with g3:
        my_audience = st.text_input("Who is it for?",     placeholder="e.g. Working professionals 25–40")

    gi1, gi2 = st.columns([2, 4])
    with gi1:
        my_ingredient = st.text_input(
            "Key Ingredient / Herb",
            placeholder="e.g. Ashwagandha root",
            help="The raw ingredient — shown visually in the image alongside the bottle",
        )
    with gi2:
        my_ingredient_benefit = st.text_input(
            "What does this ingredient do?",
            placeholder="e.g. rich in withanolides that reduce cortisol naturally",
        )

    st.markdown("**Pick an inspiration source:**")
    inspo_type = st.radio(
        "Inspiration type", ["Any Ad", "Theme", "Root", "Visual Root"],
        horizontal=True, label_visibility="collapsed",
    )

    selected_ad_data      = None
    selected_theme_data   = None
    selected_root_data    = None
    selected_visual_data  = None
    selected_vroot_data   = None

    # ── Person photo upload (available for all inspiration sources) ────────────
    st.markdown("---")
    st.markdown("**👤 Add a person to this ad (optional)**")
    st.caption("If your inspiration source uses a person/doctor/lifestyle element, upload your photo here.")
    ppc1, ppc2, ppc3 = st.columns(3)

    person_photo_path = None
    illustration_style = "realistic"

    with ppc1:
        person_use = st.radio(
            "Use uploaded photo or generated?",
            ["Generate person", "Use my doctor/person photo"],
            label_visibility="collapsed",
            key="person_radio_main"
        )

    with ppc2:
        if person_use == "Use my doctor/person photo":
            uploaded_person = st.file_uploader(
                "Upload doctor/person photo (JPG, PNG)",
                type=["jpg", "jpeg", "png"],
                key="person_photo_upload_main"
            )
            if uploaded_person:
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(uploaded_person.read())
                    person_photo_path = tmp.name
                st.caption(f"✅ Photo uploaded: {uploaded_person.name}")
                st.image(uploaded_person, width=150)

    with ppc3:
        if person_use == "Use my doctor/person photo" and person_photo_path:
            st.markdown("**Photo Style:**")
            illustration_style = st.radio(
                "Style",
                ["Realistic", "Illustrated"],
                label_visibility="collapsed",
                key="illustration_style_main",
                horizontal=True
            ).lower()

    st.markdown("---")

    _all_ads: list[dict] = list(merged) if merged else []
    if not _all_ads:
        _scored_files = sorted(DATA_SCORED.glob("*.json"),   key=lambda p: p.stat().st_mtime, reverse=True)
        _text_files   = sorted(DATA_ANALYZED.glob("*_text_analysis.json"))
        _text_map: dict = {}
        for _tf in _text_files:
            try:
                for _a in load_json(_tf):
                    if _a.get("ad_id"):
                        _text_map[_a["ad_id"]] = _a
            except Exception:
                pass
        if _scored_files:
            try:
                _sd   = load_json(_scored_files[0])
                _base = _sd.get("scored_ads", _sd) if isinstance(_sd, dict) else _sd
                for _a in _base:
                    _all_ads.append({**_a, **_text_map.get(_a.get("ad_id", ""), {})})
            except Exception:
                pass

    _winner_ads = [a for a in _all_ads if a.get("is_winner")]

    if inspo_type == "Any Ad":
        if not _all_ads:
            st.warning("No ads found. Run the pipeline first.")
        else:
            _show_winners_only = st.checkbox("Show winners only", value=False, key="gen_winners_only")
            _ads_to_show = _winner_ads if _show_winners_only else _all_ads

            def _ad_label(a: dict) -> str:
                title = (a.get("ad_creative_link_title") or a.get("ad_creative_body") or "")[:55]
                days  = a.get("run_duration_days", "?")
                score = a.get("composite_score", "")
                wt    = " 🏆" if a.get("is_winner") else ""
                score_str = f" · score {score}" if score else f" · {days}d"
                return f"{a.get('ad_id')}{wt}{score_str} — {title}"

            ad_options   = {_ad_label(a): a for a in _ads_to_show}
            chosen_label = st.selectbox(f"Pick any ad ({len(_ads_to_show)} shown)", list(ad_options.keys()))
            selected_ad_data = ad_options[chosen_label]

            with st.expander("Preview selected ad", expanded=False):
                _p1, _p2 = st.columns(2)
                with _p1:
                    st.markdown(f"**Hook:** `{selected_ad_data.get('hook_type','—')}`  "
                                f"**Tone:** `{selected_ad_data.get('emotional_tone','—')}`")
                    st.markdown(f"**Claim:** {selected_ad_data.get('core_claim','—')}")
                    st.markdown(f"**Ran:** {selected_ad_data.get('run_duration_days','?')} days")
                    st.markdown(f"**Winner:** {'✅ Yes' if selected_ad_data.get('is_winner') else '❌ No'}")
                with _p2:
                    _imgs = get_display_images(selected_ad_data)
                    if _imgs:
                        try:
                            st.image(_imgs[0], use_container_width=True)
                        except Exception:
                            pass

            # Get visual analysis for this ad
            _vpath = None
            if st.session_state.page_label:
                _vpath = DATA_ANALYZED / f"{st.session_state.page_label}_vision_analysis.json"
            else:
                _vfiles = sorted(DATA_ANALYZED.glob("*_vision_analysis.json"))
                _vpath = _vfiles[-1] if _vfiles else None
            if _vpath and Path(_vpath).exists():
                try:
                    _vdata = load_json(_vpath)
                    _vid = selected_ad_data.get("ad_id")
                    selected_visual_data = next((v for v in _vdata if v.get("ad_id") == _vid), None)
                except Exception:
                    pass

    elif inspo_type == "Theme":
        _themes_list = []
        if themes_data:
            _themes_list = themes_data.get("top_themes", [])
            for _t in _themes_list:
                _t["dominant_emotional_angle"] = themes_data.get("dominant_emotional_angle", "")
                _t["most_used_hook"] = themes_data.get("most_used_hook", "")
        if not _themes_list:
            for _tf in sorted(DATA_ANALYZED.glob("*_aggregated_themes.json")):
                try:
                    _td = load_json(_tf)
                    _tl = _td.get("top_themes", [])
                    for _t in _tl:
                        _t["dominant_emotional_angle"] = _td.get("dominant_emotional_angle", "")
                        _t["most_used_hook"] = _td.get("most_used_hook", "")
                    _themes_list.extend(_tl)
                except Exception:
                    pass
        if not _themes_list:
            st.warning("No themes found. Run Step 5 first.")
        else:
            theme_options = {t.get("theme_name", f"Theme {i}"): t for i, t in enumerate(_themes_list)}
            chosen_theme  = st.selectbox("Pick a theme", list(theme_options.keys()))
            selected_theme_data = theme_options[chosen_theme]
            with st.expander("Theme details", expanded=False):
                st.markdown(selected_theme_data.get("description", ""))
                st.markdown(f"Used in **{selected_theme_data.get('frequency','?')} ads**")

    elif inspo_type == "Root":
        _roots_source = layout_roots_data if layout_roots_data else {}
        if not _roots_source:
            for _rf in sorted(DATA_ANALYZED.glob("*_layout_roots.json")):
                try:
                    _roots_source = load_json(_rf)
                    break
                except Exception:
                    pass
        _roots_list = _roots_source.get("layout_roots", [])
        if not _roots_list:
            st.warning("No layout structures found. Run Step 7 first.")
        else:
            root_options = {
                f"{r.get('layout_emoji', r.get('root_emoji','📐'))} "
                f"{r.get('layout_name', r.get('root_name', r.get('layout_id','')))} "
                f"({r.get('ad_count') or len(r.get('ad_ids',[]))} ads)": r
                for r in _roots_list
            }
            chosen_root_label = st.selectbox("Pick a layout structure", list(root_options.keys()))
            selected_root_data = root_options[chosen_root_label]

            with st.expander("Layout details", expanded=True):
                st.markdown(f"_{selected_root_data.get('description','')}_")
                rc1, rc2 = st.columns(2)
                with rc1:
                    st.markdown(f"**Zones:** `{selected_root_data.get('zones','—')}`")
                    st.caption(selected_root_data.get("skeleton", ""))
                with rc2:
                    st.markdown(f"**Flexibility:** {selected_root_data.get('flexibility','—')}")
                brief = selected_root_data.get("structure_brief", "")
                if brief:
                    st.info(brief)
                _root_imgs = selected_root_data.get("ad_images", [])
                if _root_imgs:
                    st.markdown("**Sample ads:**")
                    _gcols = st.columns(min(len(_root_imgs), 4))
                    for _gi, _item in enumerate(_root_imgs[:4]):
                        _url = _item.get("image_url", "")
                        if _url:
                            with _gcols[_gi]:
                                try:
                                    _src = resolve_image(_url) or _url
                                    st.image(_src, use_container_width=True)
                                except Exception:
                                    pass

    else:  # Visual Root
        _vroots_source = {}
        if st.session_state.page_label:
            _vrf = DATA_ANALYZED / f"{st.session_state.page_label}_visual_roots.json"
            if _vrf.exists():
                try:
                    _vroots_source = load_json(_vrf)
                except Exception:
                    pass
        if not _vroots_source:
            for _vrf in sorted(DATA_ANALYZED.glob("*_visual_roots.json")):
                try:
                    _vroots_source = load_json(_vrf)
                    break
                except Exception:
                    pass

        _vroots_list = _vroots_source.get("visual_roots", [])
        if not _vroots_list:
            st.warning("No visual roots found. Run Step 6 first.")
        else:
            vroot_options = {
                f"{r.get('root_emoji','🖼️')} {r.get('root_name', r.get('root_id',''))} "
                f"({r.get('ad_count') or len(r.get('ad_ids',[]))} ads)": r
                for r in _vroots_list
            }
            chosen_vroot_label = st.selectbox("Pick a visual format", list(vroot_options.keys()))
            selected_vroot_data = vroot_options[chosen_vroot_label]

            with st.expander("Visual format details", expanded=True):
                st.markdown(f"_{selected_vroot_data.get('description','')}_")

                _vr_c1, _vr_c2 = st.columns(2)
                with _vr_c1:
                    st.markdown(f"**Layout:** `{selected_vroot_data.get('layout_structure','—')}`")
                    st.markdown(f"**Content:** `{selected_vroot_data.get('content_type','—')}`")
                    st.markdown(f"**Color mood:** `{selected_vroot_data.get('color_mood','—')}`")
                with _vr_c2:
                    _sat = selected_vroot_data.get('saturation_signal','—')
                    _sat_color = {"dominant": "🔴", "common": "🟡", "occasional": "🟢", "rare": "🔵"}.get(_sat, "⚪")
                    st.markdown(f"**Saturation:** {_sat_color} {_sat}")

                _brief = selected_vroot_data.get("designer_brief", "")
                if _brief:
                    st.markdown("**Designer Brief:**")
                    st.info(_brief)

                _vroot_imgs = selected_vroot_data.get("ad_images", [])
                if _vroot_imgs:
                    st.markdown("**Sample ads using this format:**")
                    _vgcols = st.columns(min(len(_vroot_imgs), 4))
                    for _vgi, _vitem in enumerate(_vroot_imgs[:4]):
                        _vurl = _vitem.get("image_url", "")
                        if _vurl:
                            with _vgcols[_vgi]:
                                try:
                                    _vsrc = resolve_image(_vurl) or _vurl
                                    st.image(_vsrc, use_container_width=True)
                                except Exception:
                                    pass

    # ── Generate button ────────────────────────────────────────────────────────
    # Check if selected source contains a person — only then use the uploaded photo
    _selected_has_person = False
    if selected_ad_data:
        desc = str(selected_ad_data.get('description', '') + selected_ad_data.get('hook_type', '')).lower()
        _selected_has_person = any(w in desc for w in ['person', 'doctor', 'lifestyle', 'authority', 'testimonial'])
    elif selected_vroot_data:
        desc = str(selected_vroot_data.get('description', '') + selected_vroot_data.get('content_type', '')).lower()
        _selected_has_person = any(w in desc for w in ['person', 'doctor', 'lifestyle', 'authority', 'testimonial'])
    elif selected_root_data:
        desc = str(selected_root_data.get('layout_name', '') + selected_root_data.get('skeleton', '')).lower()
        _selected_has_person = any(w in desc for w in ['person', 'doctor', 'lifestyle', 'authority', 'testimonial'])

    # Only pass person_photo if the selected source actually has a person
    final_person_photo = person_photo_path if _selected_has_person else None
    can_generate = bool(my_product and my_benefit and my_audience
                        and (selected_ad_data or selected_theme_data or selected_root_data or selected_vroot_data))

    if st.button("✨ Generate Ad", disabled=not can_generate, type="primary"):
        with st.spinner("Writing your ad…"):
            try:
                from ad_generator import generate as gen_ad
                result = gen_ad(
                    product_name=my_product,
                    key_benefit=my_benefit,
                    target_audience=my_audience,
                    key_ingredient=my_ingredient or None,
                    ingredient_benefit=my_ingredient_benefit or None,
                    competitor_ad=selected_ad_data,
                    theme=selected_theme_data,
                    root=selected_root_data,
                    visual_root=selected_vroot_data,
                    visual_analysis=selected_visual_data,
                    person_photo_path=final_person_photo,
                    illustration_style=illustration_style,
                )
                st.session_state["last_generated_ad"] = result
            except Exception as e:
                st.error(f"Generation failed: {e}")

    if st.session_state.get("last_generated_ad"):
        result = st.session_state["last_generated_ad"]
        st.divider()
        st.markdown("### ✅ Your Generated Ad")

        rationale = result.get("creative_rationale", "")
        if rationale:
            st.markdown(
                f'<div class="banner-green"><strong>💡 Why this approach works:</strong> {rationale}</div>',
                unsafe_allow_html=True,
            )

        r1, r2 = st.columns([1, 1])
        with r1:
            st.markdown("#### 📝 Ad Copy")
            bullets_html = ""
            for b in result.get("benefit_bullets") or []:
                bullets_html += f'<div style="margin:4px 0;color:#d1d5db;">✅ {b}</div>'
            st.markdown(
                f"""<div class="ad-box">
                <div class="ad-headline">{result.get('headline','')}</div>
                <div class="ad-body">{result.get('body_copy','')}</div>
                {bullets_html}
                <div style="margin-top:12px;"><span class="ad-cta">{result.get('cta','')}</span></div>
                </div>""",
                unsafe_allow_html=True,
            )
        with r2:
            st.markdown("#### 🖼️ Image Prompt")
            st.text_area(
                "Paste into Gemini Imagen or Midjourney",
                value=result.get("image_prompt", ""),
                height=230,
                label_visibility="collapsed",
            )
            st.caption("Select all (Ctrl+A) → Copy (Ctrl+C) → Paste into your image generator")

        with st.expander("View raw JSON output"):
            st.json(result)

        if st.button("🔄 Generate a new variation", key="regen"):
            st.session_state.pop("last_generated_ad", None)
            st.rerun()
