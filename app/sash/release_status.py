# app/sash/release_status.py
#
# Cinema / Streaming / Physical / Production (movies) and Airing / Ended /
# Cancelled (TV) status. The date-based movie logic
# (_compute_movie_status_from_dates) and the tiered cache-TTL scheme
# (release_status_expiry / _RELEASE_STATUS_TTL_DAYS) are adapted verbatim
# from PostersPlus (AGPLv3) tmdb.py + cache.py — see /NOTICE.md. Only the
# storage backend (app.cache's sqlite selection cache instead of
# PostersPlus's dedicated tables) was changed.
from __future__ import annotations

import datetime as _dt
import logging
import time

import httpx

from app.cache import get_selection, set_selection
from app.config import CINEMA_MAX_AGE_YEARS
from app.sources import tmdb as tmdb_src

logger = logging.getLogger(__name__)

# TTL tiers: the progression Cinema -> Streaming -> Physical is one-way and
# slows down as it goes, so a Physical title doesn't need re-checking often
# while a Cinema title (which might flip to Streaming any day TMDB publishes
# a digital date) needs checking daily.
_RELEASE_STATUS_TTL_DAYS = {
    "Physical": 90,
    "Cancelled": 90,
    "Ended": 60,
    "Streaming": 30,
    "Cinema": 1,
    "Production": 1,
    "Airing": 3,
}
_RELEASE_STATUS_TTL_FALLBACK_DAYS = 7
_RELEASE_BOUNDARY_MAX_WAIT_DAYS = 14

_TV_STATUS_MAP = {
    "Returning Series": "Airing",
    "In Production": "Production",
    "Planned": "Production",
    "Pilot": "Production",
    "Ended": "Ended",
    "Cancelled": "Cancelled",
    "Canceled": "Cancelled",
}


def _parse_date(value: str | None) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat((value or "")[:10])
    except (TypeError, ValueError):
        return None


def _compute_movie_status_from_dates(
    theatrical_date: _dt.date | None,
    digital_date: _dt.date | None,
    physical_date: _dt.date | None,
    tmdb_status: str | None,
) -> str:
    today = _dt.date.today()
    has_physical = physical_date is not None and physical_date <= today
    has_digital = digital_date is not None and digital_date <= today
    has_theatrical = theatrical_date is not None and theatrical_date <= today

    if has_physical:
        return "Physical"
    if has_digital:
        return "Streaming"
    if has_theatrical:
        if (
            CINEMA_MAX_AGE_YEARS > 0
            and (today - theatrical_date).days > CINEMA_MAX_AGE_YEARS * 365
        ):
            return "Streaming"
        return "Cinema"
    if tmdb_status == "Released":
        return "Streaming"
    return "Production"


def release_status_expiry(status: str | None, upcoming_dates: list[int] | None = None, now: int | None = None) -> int:
    """Seconds-from-now TTL for a cached status, clamped to the soonest known
    future release-date boundary when TMDB has already told us one."""
    now = int(time.time() if now is None else now)
    future = sorted(ts for ts in (upcoming_dates or ()) if int(ts) > now)
    if future:
        deadline = min(int(future[0]), now + _RELEASE_BOUNDARY_MAX_WAIT_DAYS * 86400)
    else:
        deadline = now + _RELEASE_STATUS_TTL_DAYS.get(status or "", _RELEASE_STATUS_TTL_FALLBACK_DAYS) * 86400
    return max(3600, deadline - now)  # never thrash on a boundary minutes away


async def _fetch_movie_release_info(client: httpx.AsyncClient, tmdb_id: str, tmdb_status: str | None) -> dict | None:
    cache_key = f"release_info:movie:{tmdb_id}"
    cached = get_selection(cache_key)
    if cached:
        cached["status"] = _compute_movie_status_from_dates(
            _parse_date(cached.get("theatrical_date")),
            _parse_date(cached.get("digital_date")),
            _parse_date(cached.get("physical_date")),
            tmdb_status,
        )
        return cached

    if tmdb_status in ("In Production", "Post Production", "Planned", "Rumored"):
        return {"status": "Production"}
    if tmdb_status == "Cancelled":
        return {"status": "Cancelled"}

    data = await tmdb_src.get_release_dates(client, tmdb_id)
    if not data:
        return None

    earliest_theatrical = earliest_digital = earliest_physical = latest_digital = None
    for entry in data.get("results", []):
        for rd in entry.get("release_dates", []):
            rtype = rd.get("type")
            rdate = _parse_date(rd.get("release_date"))
            if rdate is None:
                continue
            if rtype == 5:
                earliest_physical = min(filter(None, (earliest_physical, rdate)), default=rdate)
            elif rtype in (4, 6):
                earliest_digital = min(filter(None, (earliest_digital, rdate)), default=rdate)
                latest_digital = max(filter(None, (latest_digital, rdate)), default=rdate)
            elif rtype == 3:
                earliest_theatrical = min(filter(None, (earliest_theatrical, rdate)), default=rdate)

    status = _compute_movie_status_from_dates(earliest_theatrical, earliest_digital, earliest_physical, tmdb_status)
    info = {
        "status": status,
        "theatrical_date": earliest_theatrical.isoformat() if earliest_theatrical else None,
        "digital_date": earliest_digital.isoformat() if earliest_digital else None,
        "physical_date": earliest_physical.isoformat() if earliest_physical else None,
        "digital_latest_date": latest_digital.isoformat() if latest_digital else None,
    }

    upcoming = []
    today = _dt.date.today()
    for key in ("theatrical_date", "digital_date", "physical_date"):
        parsed = _parse_date(info.get(key))
        if parsed and parsed > today:
            upcoming.append(int(_dt.datetime.combine(parsed, _dt.time.min).timestamp()))
    set_selection(cache_key, info, release_status_expiry(status, upcoming))
    return info


async def fetch_release_status(client: httpx.AsyncClient, media_type: str, tmdb_id: str, tmdb_status: str | None) -> str | None:
    """One of "Physical"|"Streaming"|"Cinema"|"Production"|"Airing"|"Ended"|
    "Cancelled", or None if it can't be determined."""
    if media_type == "tv":
        return _TV_STATUS_MAP.get(tmdb_status or "")

    info = await _fetch_movie_release_info(client, tmdb_id, tmdb_status)
    return (info or {}).get("status")


async def fetch_recent_digital_release_date(
    client: httpx.AsyncClient, tmdb_id: str, tmdb_status: str | None, *, max_age_days: int = 14
) -> str | None:
    """Most recent digital/TV-broadcast date, if within *max_age_days* — used
    for the "just added"/"newly streaming" freshness signal."""
    info = await _fetch_movie_release_info(client, tmdb_id, tmdb_status)
    if not info:
        return None
    digital = _parse_date(info.get("digital_latest_date") or info.get("digital_date"))
    if digital is None:
        return None
    age = (_dt.date.today() - digital).days
    return digital.isoformat() if 0 <= age <= max_age_days else None
