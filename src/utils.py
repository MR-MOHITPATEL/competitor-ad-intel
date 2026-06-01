import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

# Load .env from the project root (competitor-ad-intel/) regardless of CWD
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_SUPABASE_BUCKET = "ad-intel-data"
_logger = logging.getLogger("utils")


# ── Supabase helpers ───────────────────────────────────────────────────────────

def _supabase_client():
    """Return a Supabase client if SUPABASE_URL + SUPABASE_KEY are set, else None."""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not (url and key):
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        _logger.warning("supabase package not installed — running local-only mode.")
        return None


def _storage_key(path: Path) -> str:
    """Convert absolute local path → Supabase storage key (relative to project root)."""
    try:
        rel = path.relative_to(_PROJECT_ROOT)
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


# ── Core JSON I/O (with Supabase write-through) ────────────────────────────────

def save_json(data: dict | list, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    sb = _supabase_client()
    if sb:
        key = _storage_key(path)
        try:
            sb.storage.from_(_SUPABASE_BUCKET).upload(
                key,
                content.encode("utf-8"),
                {"upsert": "true", "content-type": "application/json"},
            )
            _logger.debug("Supabase: uploaded %s", key)
        except Exception as e:
            _logger.warning("Supabase upload failed for %s: %s", key, e)


def load_json(path: str | Path) -> dict | list:
    path = Path(path)

    # Fast path: local file exists
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback: try Supabase
    sb = _supabase_client()
    if sb:
        key = _storage_key(path)
        try:
            raw = sb.storage.from_(_SUPABASE_BUCKET).download(key)
            parsed = json.loads(raw)
            # Cache locally so subsequent reads are instant
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)
            _logger.debug("Supabase: pulled and cached %s", key)
            return parsed
        except Exception as e:
            _logger.debug("Supabase download failed for %s: %s", key, e)

    raise FileNotFoundError(f"JSON file not found: {path}")


def sync_from_supabase(project_root: Path | None = None) -> int:
    """
    Download all data files from Supabase to local disk.
    Called once at dashboard startup so Path.glob() and path.exists() work normally.
    Returns the number of files synced.
    """
    sb = _supabase_client()
    if not sb:
        return 0

    root = project_root or _PROJECT_ROOT
    synced = 0

    # Prefixes to sync — images are NOT synced (too large; vision uses URLs instead)
    prefixes = [
        "data/raw/master",
        "data/scored",
        "data/analyzed",
    ]

    for prefix in prefixes:
        try:
            # list() only returns direct children — use limit+offset to get all
            items = sb.storage.from_(_SUPABASE_BUCKET).list(
                prefix, {"limit": 500, "offset": 0}
            )
            for item in items or []:
                name = item.get("name", "")
                if not name:
                    continue
                # Item is a sub-folder — recurse one level
                if not name.endswith(".json"):
                    sub_prefix = f"{prefix}/{name}"
                    try:
                        sub_items = sb.storage.from_(_SUPABASE_BUCKET).list(
                            sub_prefix, {"limit": 500, "offset": 0}
                        )
                        for sub in sub_items or []:
                            sub_name = sub.get("name", "")
                            if sub_name and sub_name.endswith(".json"):
                                key = f"{sub_prefix}/{sub_name}"
                                local_path = root / key
                                if local_path.exists():
                                    continue
                                try:
                                    raw = sb.storage.from_(_SUPABASE_BUCKET).download(key)
                                    local_path.parent.mkdir(parents=True, exist_ok=True)
                                    local_path.write_bytes(raw)
                                    synced += 1
                                    _logger.debug("Supabase sync: pulled %s", key)
                                except Exception as e:
                                    _logger.warning("Supabase sync: failed to pull %s — %s", key, e)
                    except Exception as e:
                        _logger.warning("Supabase sync: failed to list %s — %s", sub_prefix, e)
                    continue
                key = f"{prefix}/{name}"
                local_path = root / key
                if local_path.exists():
                    continue  # already cached
                try:
                    raw = sb.storage.from_(_SUPABASE_BUCKET).download(key)
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(raw)
                    synced += 1
                    _logger.debug("Supabase sync: pulled %s", key)
                except Exception as e:
                    _logger.warning("Supabase sync: failed to pull %s — %s", key, e)
        except Exception as e:
            _logger.warning("Supabase sync: failed to list %s — %s", prefix, e)

    if synced:
        _logger.info("Supabase sync: pulled %d new file(s) from cloud storage.", synced)
    return synced


# ── Other utilities ────────────────────────────────────────────────────────────

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class GroqKeyPool:
    """Rotates through GROQ_API_KEY_1 / _2 / _3 on 413 or 429 errors.

    Falls back to GROQ_API_KEY if no numbered keys are set.
    Call pool.rotate() on error; it returns False when all keys are exhausted.
    """

    _RETRIABLE = ("413", "429", "rate_limit", "payload_too_large", "payload too large")

    def __init__(self) -> None:
        keys: list[str] = []
        for i in range(1, 10):
            k = os.getenv(f"GROQ_API_KEY_{i}")
            if k:
                keys.append(k)
        if not keys:
            legacy = os.getenv("GROQ_API_KEY")
            if legacy:
                keys = [legacy]
            else:
                raise EnvironmentError(
                    "No Groq API keys found. Set GROQ_API_KEY_1 (and optionally _2, _3) in .env"
                )
        self._keys = keys
        self._idx = 0
        self._start_idx = 0
        self._logger = logging.getLogger("groq_key_pool")
        self._logger.info("GroqKeyPool ready — %d key(s) loaded", len(keys))

    @property
    def client(self) -> Groq:
        return Groq(api_key=self._keys[self._idx])

    def rotate(self) -> bool:
        next_idx = (self._idx + 1) % len(self._keys)
        if next_idx == self._start_idx:
            return False
        self._logger.warning(
            "Key %d/%d failed — switching to key %d/%d",
            self._idx + 1, len(self._keys),
            next_idx + 1, len(self._keys),
        )
        self._idx = next_idx
        return True

    def reset_rotation(self) -> None:
        self._start_idx = self._idx

    @staticmethod
    def is_retriable(error: str) -> bool:
        err_lower = error.lower()
        return any(tag in err_lower for tag in GroqKeyPool._RETRIABLE)

    def __len__(self) -> int:
        return len(self._keys)


def get_env(key: str, required: bool = True) -> str:
    value = os.getenv(key)
    if required and not value:
        raise EnvironmentError(f"Missing required environment variable: {key}")
    return value or ""


def timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def find_latest_file(directory: str | Path, pattern: str) -> Path | None:
    directory = Path(directory)
    matches = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None
