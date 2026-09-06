# app/sources/metahub.py
#
# images.metahub.space serves community/Cinemeta-sourced art keyed by imdb
# id. It only publishes posters and backgrounds (no logos) — an existence
# check (HEAD request) is used since it 404s cleanly for titles it doesn't
# have art for, rather than returning a placeholder.
from __future__ import annotations

import logging

import httpx

from app.config import HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_BASE = "https://images.metahub.space"


def poster_url(imdb_id: str) -> str:
    return f"{_BASE}/poster/medium/{imdb_id}/img"


def backdrop_url(imdb_id: str) -> str:
    return f"{_BASE}/background/medium/{imdb_id}/img"


async def _exists(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def resolve_poster(client: httpx.AsyncClient, imdb_id: str | None) -> str | None:
    if not imdb_id:
        return None
    url = poster_url(imdb_id)
    return url if await _exists(client, url) else None


async def resolve_backdrop(client: httpx.AsyncClient, imdb_id: str | None) -> str | None:
    if not imdb_id:
        return None
    url = backdrop_url(imdb_id)
    return url if await _exists(client, url) else None
