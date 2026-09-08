# app/config.py
#
# All configuration comes from environment variables (set via .env / compose).
# effective_cpus() and the SASH_PRIORITY list below are taken directly from
# PostersPlus (AGPLv3) config.py — see /NOTICE.md.
import os


def _bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, str(default)))
    except ValueError:
        return default


def effective_cpus() -> int:
    """Cores this process may actually use, honouring a Docker/compose `cpus:`
    limit (enforced via CFS quota, invisible to os.cpu_count()).

    Adapted verbatim from PostersPlus config.py.
    """
    limits = []
    try:  # cgroup v2
        raw = open("/sys/fs/cgroup/cpu.max").read().split()
        if raw[0] != "max":
            limits.append(int(raw[0]) / int(raw[1]))
    except Exception:
        pass
    try:  # cgroup v1
        quota = int(open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read())
        period = int(open("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read())
        if quota > 0 and period > 0:
            limits.append(quota / period)
    except Exception:
        pass
    try:
        limits.append(len(os.sched_getaffinity(0)))
    except Exception:
        pass
    limits.append(os.cpu_count() or 1)
    return max(1, int(min(limits)))


EFFECTIVE_CPUS = effective_cpus()

# ---------------------------------------------------------------------------
# Paths / storage
# ---------------------------------------------------------------------------
CACHE_DIR = os.environ.get("CACHE_DIR", "/app/cache").rstrip("/")
DB_PATH = f"{CACHE_DIR}/cache.db"
IMAGE_CACHE_DIR = f"{CACHE_DIR}/images"
DISCOVERY_OVERRIDES_PATH = os.environ.get(
    "DISCOVERY_OVERRIDES_PATH", f"{CACHE_DIR}/discovery_overrides.json"
)

# ---------------------------------------------------------------------------
# Release status (Cinema / Streaming / Physical / Production / Airing / Ended
# / Cancelled) — adapted from PostersPlus tmdb.py + cache.py.
# ---------------------------------------------------------------------------
# A theatrical-only film older than this many years is treated as Streaming
# rather than staying "Cinema" forever (0 disables the downgrade).
CINEMA_MAX_AGE_YEARS = max(0, _int("CINEMA_MAX_AGE_YEARS", 3))
# Optional r/movieleaks-derived early "already streaming" signal — see
# app/sash/digital_release.py. Off by default: it calls a third-party
# archive API (Arctic Shift) outside TMDB/TVDB/Metahub/MDBList.
DIGITAL_RELEASE_ENABLED = _bool("DIGITAL_RELEASE_ENABLED", False)
DIGITAL_RELEASE_MIN_AGE_DAYS = max(0, _int("DIGITAL_RELEASE_MIN_AGE_DAYS", 1))
DIGITAL_RELEASE_MAX_AGE_DAYS = max(1, _int("DIGITAL_RELEASE_MAX_AGE_DAYS", 30))

# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
ACCESS_KEY = os.environ.get("ACCESS_KEY", "").strip()  # optional ?access_key= gate on /stats etc.

# ---------------------------------------------------------------------------
# Upstream API keys
# ---------------------------------------------------------------------------
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
# TMDB "language" used for the primary art pass. Original-language fallback is
# always attempted regardless of this value.
TMDB_PRIMARY_LANGUAGE = os.environ.get("TMDB_PRIMARY_LANGUAGE", "en").strip()

TVDB_API_KEY = os.environ.get("TVDB_API_KEY", "").strip()
TVDB_SUBSCRIBER_PIN = os.environ.get("TVDB_SUBSCRIBER_PIN", "").strip()

# Optional. Only needed for MDBList-derived award/keyword signals (cult,
# true-story, metacritic must-see, best-picture win/nom keywords). Golden
# Globe / Emmy / festival sashes work without a key since they resolve off
# curated TMDB-id sets. Two keys supported for basic key rotation.
MDBLIST_API_KEY = os.environ.get("MDBLIST_API_KEY", "").strip()
MDBLIST_API_KEY_2 = os.environ.get("MDBLIST_API_KEY_2", "").strip()
MDBLIST_API_KEYS = [k for k in (MDBLIST_API_KEY, MDBLIST_API_KEY_2) if k]
MDBLIST_CONCURRENCY = _int("MDBLIST_CONCURRENCY", 3)

# ---------------------------------------------------------------------------
# Image sizes
# ---------------------------------------------------------------------------
# TMDB size tokens: posters — w92/w154/w185/w342/w500/w780/original
#                   backdrops/logos — w300/w780/w1280/original
TMDB_POSTER_SIZE = os.environ.get("TMDB_POSTER_SIZE", "w780").strip()
TMDB_BACKDROP_SIZE = os.environ.get("TMDB_BACKDROP_SIZE", "original").strip()
TMDB_LOGO_SIZE = os.environ.get("TMDB_LOGO_SIZE", "original").strip()

# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------
# How long a resolved art *selection* (which URL/source won the fallback
# chain) is cached before being re-evaluated, in hours.
SELECTION_CACHE_TTL_HOURS = _int("SELECTION_CACHE_TTL_HOURS", 24)
# How long a negative result (nothing found anywhere) is cached, in hours —
# short, so a title that just got added doesn't stay "missing" all day.
NEGATIVE_CACHE_TTL_HOURS = _int("NEGATIVE_CACHE_TTL_HOURS", 3)
# How long a rendered sash overlay (image bytes) is cached, in hours.
RENDER_CACHE_TTL_HOURS = _int("RENDER_CACHE_TTL_HOURS", 24)
# HTTP cache headers sent with every image response.
HTTP_CACHE_MAX_AGE_SECONDS = _int("HTTP_CACHE_MAX_AGE_SECONDS", 86400)

# ---------------------------------------------------------------------------
# Resource / concurrency ("cpu intensity")
# ---------------------------------------------------------------------------
# Upper bound on concurrent CPU-bound render jobs (color sampling + sash
# drawing) run in a worker thread pool. "auto" picks EFFECTIVE_CPUS.
_render_workers_raw = os.environ.get("RENDER_WORKERS", "auto").strip().lower()
RENDER_WORKERS = EFFECTIVE_CPUS if _render_workers_raw == "auto" else max(1, _int("RENDER_WORKERS", EFFECTIVE_CPUS))
# Max concurrent outbound requests to each upstream (TMDB/TVDB/Metahub).
UPSTREAM_CONCURRENCY = _int("UPSTREAM_CONCURRENCY", max(4, EFFECTIVE_CPUS * 4))
HTTP_TIMEOUT_SECONDS = _float("HTTP_TIMEOUT_SECONDS", 12.0)

# ---------------------------------------------------------------------------
# IMDb ratings dataset (top-rated sash) — adapted from PostersPlus
# imdb_dataset.py behaviour/env names.
# ---------------------------------------------------------------------------
IMDB_DATASET_ENABLED = _bool("IMDB_DATASET_ENABLED", True)
IMDB_DATASET_PATH = os.environ.get("IMDB_DATASET_PATH", f"{CACHE_DIR}/imdb_ratings.db")
IMDB_DATASET_REFRESH_HOURS = max(1, _int("IMDB_DATASET_REFRESH_HOURS", 24))
IMDB_DATASET_MIN_VOTES = max(0, _int("IMDB_DATASET_MIN_VOTES", 1000))
# Minimum 0-10 rating (on IMDb's scale) to be considered "Top Rated".
# User asked for "anything above 85" on a 0-100 scale -> 8.5 on IMDb's 0-10.
TOP_RATED_MIN_SCORE = _float("TOP_RATED_MIN_SCORE", 8.5)

# ---------------------------------------------------------------------------
# Trending source — TMDB's own trending endpoint by default, or point at an
# MDBList list URL (no MDBList API key required) or any TMDB-shaped
# {"results":[...]} endpoint. Same two payload shapes / URL-rewrite rule as
# PostersPlus's TRENDING_SOURCE_* — see app/trending.py.
# ---------------------------------------------------------------------------
TRENDING_SOURCE_MOVIE = os.environ.get("TRENDING_SOURCE_MOVIE", "").strip()
TRENDING_SOURCE_TV = os.environ.get("TRENDING_SOURCE_TV", "").strip()
TRENDING_SOURCE_MAX_ITEMS = max(1, _int("TRENDING_SOURCE_MAX_ITEMS", 500))
TRENDING_CACHE_TTL_HOURS = _int("TRENDING_CACHE_TTL_HOURS", 1)
TRENDING_FETCH_COUNT = _int("TRENDING_FETCH_COUNT", 40)
TRENDING_BROAD_FETCH_COUNT = _int("TRENDING_BROAD_FETCH_COUNT", 100)

# ---------------------------------------------------------------------------
# Sash rendering
# ---------------------------------------------------------------------------
SASH_ENABLED = _bool("SASH_ENABLED", True)
# "sash" (bottom line + rounded tab, this project's default) — kept as a
# named mode in case other shapes are added later.
SASH_MODE = os.environ.get("SASH_MODE", "sash").strip().lower()
SASH_HEIGHT_RATIO = _float("SASH_HEIGHT_RATIO", 0.034)  # tab height / poster height
SASH_FONT_SIZE_RATIO = _float("SASH_FONT_SIZE_RATIO", 0.62)
SASH_BASELINE_HEIGHT_RATIO = _float("SASH_BASELINE_HEIGHT_RATIO", 0.0113)  # thin line height
SASH_FROST_SATURATION = _float("SASH_FROST_SATURATION", 1.2)
SASH_TEXT_COLOR = os.environ.get("SASH_TEXT_COLOR", "").strip() or None  # "#RRGGBB" override
# One of the .ttf filenames in /fonts: Inter-Bold.ttf, Oswald-Bold.ttf,
# Ubuntu-Bold.ttf, BebasNeue-Bold.ttf (bundled from PostersPlus's font set —
# none of these are a perfect match for Apple TV+'s own SF Pro badges, which
# aren't redistributable; Oswald-Bold was picked as the closest available).
SASH_FONT = os.environ.get("SASH_FONT", "Oswald-Bold.ttf").strip()

# Priority order for "one interesting thing" sash selection — first match
# wins. Copied verbatim from PostersPlus config.py SASH_PRIORITY (the same
# slot names app/sash/discovery.py._evaluate_slot understands), reordered to
# the sequence requested for PosterBridge.
SASH_PRIORITY: list[str] = [
    "trending",
    "wins",           # Best Picture / major Emmy win
    "gg_wins",        # Major Golden Globe win
    "festival",       # Festival win
    "pic_noms",       # Best Picture / major Emmy nom
    "metacritic",     # Metacritic must-see
    "gg_noms",        # Golden Globe nom
    "top_rated",      # IMDb dataset, see TOP_RATED_MIN_SCORE
    "premiere",
    "new_release",    # "newly streaming" / "just added" combined signal
    "just_added",
    "new_season",
    "season_finale",
    "studio",         # notable studio
    "director",       # notable director
    "cast",           # notable cast
    "cult",           # cult classic
    "true_story",
    "short_film",
    "mini_series",
    "binge_ready",
    "returning",
    "airing",
    "cancelled",
    "ended",
    "cinema",
    # Supported but not enabled by default — every slot below is fully
    # wired up in app/sash/discovery.py, just not part of the requested
    # default order. Add any of them to SASH_PRIORITY in .env to enable:
    #   "trending_broad" — wider trending window than "trending"
    #   "foreign"         — non-English original-language film
    #   "physical"        — movie: on physical media
    #   "streaming"       — movie: on a streaming service (unlike "cinema"
    #                       above, this is time-boxed release-status, not a
    #                       structural fallback)
    #   "production"      — movie: not yet released
]

SASH_PRIORITY_RAW = os.environ.get("SASH_PRIORITY")  # comma-separated override, parsed in app/sash/engine.py

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = _int("PORT", 8000)
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = _float("GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", 20.0)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").strip().lower()
