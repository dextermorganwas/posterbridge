# app/trending.py
#
# "Where trending comes from" — TMDB's own /trending endpoint by default, or
# an operator-supplied URL. Two payload shapes are accepted:
#   TMDB-shaped:  {"results": [{"id": 603}, ...]}          ranked by order
#   MDBList:      [{"id": 603, "rank": 1000, "mediatype": "movie"}, ...]
#                 ranked by "rank" — paste a human MDBList list URL
#                 (https://mdblist.com/lists/<user>/<slug>) and it is
#                 rewritten to its /json export automatically. No MDBList
#                 API key required for this — public lists' JSON export is
#                 unauthenticated.
# Adapted from PostersPlus (AGPLv3) tmdb.py's trending-source handling — see
# /NOTICE.md.
from __future__ import annotations

import logging
import re
import time

import httpx

from app.cache import get_selection, set_selection
from app.config import (
    TRENDING_SOURCE_MOVIE,
    TRENDING_SOURCE_TV,
    TRENDING_SOURCE_MAX_ITEMS,
    TRENDING_CACHE_TTL_HOURS,
    HTTP_TIMEOUT_SECONDS,
)
from app.sources import tmdb as tmdb_src

logger = logging.getLogger(__name__)

_MDBLIST_LIST_RE = re.compile(
    r"^https?://(?:www\.)?mdblist\.com/lists/(?P<path>[^?#]+)", re.IGNORECASE
)


def _source_url(media_type: str) -> str:
    return TRENDING_SOURCE_TV if media_type == "tv" else TRENDING_SOURCE_MOVIE


def _normalise_url(url: str) -> str:
    url = url.strip()
    match = _MDBLIST_LIST_RE.match(url)
    if not match:
        return url
    path = match.group("path").strip("/")
    if path.endswith("/json"):
        path = path[: -len("/json")]
    if not path:
        return url
    return f"https://mdblist.com/lists/{path}/json"


def _parse_payload(payload, media_type: str) -> list[str]:
    if isinstance(payload, dict):
        items, ranked = payload.get("results"), False
    else:
        items, ranked = payload, True
    if not isinstance(items, list):
        return []

    wanted = "show" if media_type == "tv" else "movie"
    rows: list[tuple[float, str]] = []
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("mediatype") or item.get("media_type") or "").lower()
        if kind:
            if kind in ("tv", "series"):
                kind = "show"
            if kind != wanted:
                continue
        raw = item.get("id", item.get("tmdb_id", item.get("tmdbid")))
        if raw is None or not str(raw).isdigit():
            continue
        order = item.get("rank") if ranked else None
        rows.append((float(order) if isinstance(order, (int, float)) else position, str(raw)))

    rows.sort(key=lambda r: r[0])
    seen: set[str] = set()
    out: list[str] = []
    for _order, tmdb_id in rows:
        if tmdb_id not in seen:
            seen.add(tmdb_id)
            out.append(tmdb_id)
        if len(out) >= TRENDING_SOURCE_MAX_ITEMS:
            break
    return out


async def get_trending_ids(client: httpx.AsyncClient, media_type: str) -> list[str]:
    """Ordered list of TMDB ids. Cached for TRENDING_CACHE_TTL_HOURS."""
    cache_key = f"trending:{media_type}"
    cached = get_selection(cache_key)
    if cached is not None:
        return cached

    url = _source_url(media_type)
    ids: list[str]
    if url:
        try:
            resp = await client.get(_normalise_url(url), timeout=HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            ids = _parse_payload(resp.json(), media_type)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(f"Trending source failed for {media_type}: {exc}")
            ids = []
    else:
        ids = await tmdb_src.trending(client, media_type)

    set_selection(cache_key, ids, TRENDING_CACHE_TTL_HOURS * 3600)
    return ids


async def trending_rank(client: httpx.AsyncClient, media_type: str, tmdb_id: str) -> int | None:
    ids = await get_trending_ids(client, media_type)
    try:
        return ids.index(tmdb_id) + 1
    except ValueError:
        return None
