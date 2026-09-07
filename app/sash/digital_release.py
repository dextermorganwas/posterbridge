# app/sash/digital_release.py
#
# Adapted near-verbatim from PostersPlus (AGPLv3) digital_release.py — see
# /NOTICE.md. Only the storage call (app.cache.add_digital_releases instead
# of PostersPlus's own cache module) was changed. Off by default
# (DIGITAL_RELEASE_ENABLED=false) since it calls a third-party archive API.
"""
Polls r/movieleaks every 24 hours via the Arctic Shift archive API to build a
set of IMDb IDs for movies that have recently hit digital/streaming.

Arctic Shift is used instead of Reddit's JSON endpoint because Reddit blocks
unauthenticated requests from datacenter IPs (Oracle, AWS, GCP, etc.).

Posts younger than MIN_AGE_DAYS are skipped — mod cleanup usually completes
within a few hours, so a 1-day hold filters any noise before it reaches the
DB. Entries older than MAX_AGE_DAYS are pruned separately.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx

from app.cache import add_digital_releases, prune_digital_releases
from app.config import DIGITAL_RELEASE_MAX_AGE_DAYS, DIGITAL_RELEASE_MIN_AGE_DAYS

logger = logging.getLogger(__name__)

_ARCTIC_SHIFT_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
_IMDB_RE = re.compile(r"tt\d{1,10}(?!\d)")
_LIMIT = 100
_MAX_PAGES = 10
_POLL_INTERVAL = 86400
_PAGE_PAUSE = 1.0


async def _fetch_page(client: httpx.AsyncClient, after_ts: int, before_ts: int) -> list[dict]:
    try:
        resp = await client.get(
            _ARCTIC_SHIFT_URL,
            params={"subreddit": "movieleaks", "after": after_ts, "before": before_ts, "limit": _LIMIT},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as exc:
        logger.warning(f"Digital release: Arctic Shift fetch failed: {exc}")
        return []


async def sync_digital_releases(client: httpx.AsyncClient) -> int:
    now = int(time.time())
    before_ts = now - DIGITAL_RELEASE_MIN_AGE_DAYS * 86400
    after_ts = now - DIGITAL_RELEASE_MAX_AGE_DAYS * 86400

    entries: list[tuple[str, int]] = []
    cursor = before_ts

    for page_num in range(_MAX_PAGES):
        posts = await _fetch_page(client, after_ts=after_ts, before_ts=cursor)
        if not posts:
            break
        for post in posts:
            created_utc = post.get("created_utc")
            if not created_utc:
                continue
            posted_at = int(created_utc)
            haystack = " ".join((
                post.get("selftext", "") or "",
                post.get("title", "") or "",
                post.get("url", "") or "",
            ))
            for imdb_id in set(_IMDB_RE.findall(haystack)):
                entries.append((imdb_id, posted_at))
        if len(posts) < _LIMIT:
            break
        cursor = int(posts[-1].get("created_utc", cursor)) - 1
        if page_num < _MAX_PAGES - 1:
            await asyncio.sleep(_PAGE_PAUSE)

    added = add_digital_releases(entries)
    prune_digital_releases(DIGITAL_RELEASE_MAX_AGE_DAYS)
    logger.info(f"Digital release sync: {added} new entries added ({len(entries)} valid posts scanned)")
    return added


async def digital_release_poll_loop(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await sync_digital_releases(client)
        except Exception as exc:
            logger.error(f"Digital release poll loop error: {exc}")
        await asyncio.sleep(_POLL_INTERVAL)
