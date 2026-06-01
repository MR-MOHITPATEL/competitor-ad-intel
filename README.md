# Competitor Ad Intelligence — Health & Wellness

Fetch competitor ads from the Meta Ads Library, rank them by run duration (a free proxy for "this ad is working"), then use Claude AI to extract themes, emotional angles, and strategic patterns — with minimal API cost.

---

## How It Works

```
Meta Ads Library API
        ↓
  fetcher.py        →  data/raw/{page}_{timestamp}.json
        ↓
  scorer.py         →  data/scored/{page}_scored.json
        ↓
  text_analyzer.py  →  data/analyzed/{page}_text_analysis.json   (batched, 1 call per 10 ads)
  vision_analyzer.py→  data/analyzed/{page}_vision_analysis.json (only winner ads)
  aggregator.py     →  data/analyzed/{page}_aggregated_themes.json (1 final Claude call)
        ↓
  dashboard/app.py  →  Streamlit UI
```

**Cost optimization built-in:**
- Images are only sent to Claude if `is_winner = True` (top 20% by run duration)
- Text analysis is batched — 10 ads per API call
- All results are cached — re-runs skip analysis unless `--force` is passed

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `META_ACCESS_TOKEN` | Meta Developer Portal — create an app, generate a User or System Access Token with `ads_read` permission |
| `META_API_VERSION` | Default `v19.0` — check [Meta API changelog](https://developers.facebook.com/docs/graph-api/changelog) for latest |

### 3. Get a Meta Access Token

1. Go to [developers.facebook.com](https://developers.facebook.com) → Create App → Business type
2. Add the **Marketing API** product
3. Generate a **User Access Token** with the `ads_read` permission
4. For long-lived use, exchange for a **System User token** via Business Manager

---

## Usage

### Full pipeline (recommended)

```bash
python main.py --page "HimsHers" --fetch --score --analyze --dashboard
```

### Run steps independently

```bash
# Fetch only
python main.py --page "HimsHers" --fetch

# Score a specific file
python main.py --page "HimsHers" --score

# Analyze (uses cached results if available)
python main.py --page "HimsHers" --analyze

# Force re-analysis (ignore cache)
python main.py --page "HimsHers" --analyze --force

# Open dashboard only (after analysis is complete)
python main.py --dashboard
```

### Run modules directly

```bash
python src/fetcher.py --page "HimsHers"
python src/scorer.py --raw-dir data/raw
python src/text_analyzer.py --scored-file data/scored/himsors_scored.json
python src/vision_analyzer.py --scored-file data/scored/himsors_scored.json
python src/aggregator.py --page-label himsors
streamlit run dashboard/app.py
```

---

## Project Structure

```
competitor-ad-intel/
├── src/
│   ├── fetcher.py          # Fetches ads from Meta Ads Library API
│   ├── scorer.py           # Scores by run duration, flags top 20% as winners
│   ├── text_analyzer.py    # Batch Claude analysis of ad copy (10 ads/call)
│   ├── vision_analyzer.py  # Claude vision analysis for winner ads only
│   ├── aggregator.py       # Single Claude call to find root themes
│   └── utils.py            # Shared helpers
├── data/
│   ├── raw/                # Raw fetched ads
│   ├── scored/             # Scored + ranked ads
│   └── analyzed/           # AI analysis outputs
├── dashboard/
│   └── app.py              # Streamlit dashboard
├── main.py                 # CLI entry point
├── .env.example
├── requirements.txt
└── README.md
```

---

## Dashboard Tabs

| Tab | Contents |
|---|---|
| **All Ads** | Full table: hook type, emotional tone, core claim, run days, winner badge |
| **Themes** | Aggregated theme cards, dominant angles, underused opportunities |
| **Winners Only** | Top 20% ads with full text + visual analysis |

---

## Output Examples

### `_text_analysis.json`
```json
[
  {
    "ad_id": "123456789",
    "hook_type": "pain-point",
    "emotional_tone": "hope",
    "core_claim": "Clinically-backed formula that reverses hair thinning in 90 days",
    "target_audience_signal": "Men 30-50 experiencing early hair loss",
    "cta_style": "direct"
  }
]
```

### `_aggregated_themes.json`
```json
{
  "top_themes": [
    {
      "theme_name": "Clinical Credibility",
      "frequency": 14,
      "description": "Heavy use of doctor-backed claims and clinical study references",
      "example_ad_ids": ["123", "456", "789"]
    }
  ],
  "dominant_emotional_angle": "hope",
  "most_used_hook": "pain-point",
  "underused_angles": ["community belonging", "ritual/lifestyle framing"],
  "root_message": "You are losing something that defines your confidence, and we have the clinical solution"
}
```

---

## Caching Behavior

| File exists? | `--force`? | Action |
|---|---|---|
| No | — | Run analysis |
| Yes | No | Skip (use cache) |
| Yes | Yes | Re-run, overwrite |

---

## Notes

- The Meta Ads Library API only returns data for ads that have run active delivery. Spend and impressions are returned as ranges (lower/upper bounds), not exact figures.
- `is_winner` is determined per batch — it's relative to the competitor you're analyzing, not an absolute benchmark.
- Vision analysis uses `ad_snapshot_url` which is a publicly accessible URL from Meta. Some URLs may expire; re-fetching raw data will refresh them.
