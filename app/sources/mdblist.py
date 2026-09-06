# app/sources/mdblist.py
#
# Optional. Only used for the keyword-based sash signals PostersPlus also
# sources from MDBList: Oscar best-picture win/nom keywords, cult classic,
# based-on-true-story, and metacritic must-see. Golden Globe/Emmy/festival
# sashes do NOT need this — they resolve from the curated TMDB-id sets in
# app/sash/awards_data.py / app/sash/festivals.py. Endpoint and response
# shape adapted from PostersPlus (AGPLv3) ratings.py — see /NOTICE.md.
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import MDBLIST_API_KEYS, MDBLIST_CONCURRENCY, HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None


def enabled() -> bool:
    return bool(MDBLIST_API_KEYS)


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MDBLIST_CONCURRENCY)
    return _semaphore


async def fetch_keywords(client: httpx.AsyncClient, media_type: str, tmdb_id: str) -> list[dict]:
    """List of {"name": ...} keyword objects for this title, or [] if
    MDBList isn't configured or the lookup fails."""
    if not enabled():
        return []
    mdb_type = "show" if media_type == "tv" else "movie"
    async with _get_semaphore():
        try:
            resp = await client.get(
                f"https://api.mdblist.com/tmdb/{mdb_type}/{tmdb_id}",
                params={"apikey": MDBLIST_API_KEYS[0], "append_to_response": "keyword"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code != 200:
                return []
            return resp.json().get("keywords") or []
        except httpx.HTTPError as exc:
            logger.warning(f"MDBList keyword lookup failed for {tmdb_id}: {exc}")
            return []
