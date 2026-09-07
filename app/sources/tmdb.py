# app/sources/tmdb.py
#
# Thin async TMDB client: id resolution (/find), images, details+credits+
# keywords (for the sash engine), and the global trending endpoint.
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import TMDB_API_KEY, HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_BASE = "https://api.themoviedb.org/3"


def enabled() -> bool:
    return bool(TMDB_API_KEY)


def _endpoint(media_type: str) -> str:
    return "tv" if media_type == "tv" else "movie"


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict | None:
    if not enabled():
        return None
    q = {"api_key": TMDB_API_KEY, **(params or {})}
    try:
        resp = await client.get(f"{_BASE}{path}", params=q, timeout=HTTP_TIMEOUT_SECONDS)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        logger.warning(f"TMDB request failed ({path}): {exc}")
        return None


async def resolve_tmdb_id(
    client: httpx.AsyncClient,
    *,
    tmdb_id: str | None,
    imdb_id: str | None,
    tvdb_id: str | None,
    media_type: str | None,
) -> tuple[str, str] | None:
    """Return (tmdb_id, media_type), resolving via /find when only an
    imdb/tvdb id is available. Returns None if nothing could be resolved.
    """
    if tmdb_id:
        return tmdb_id, media_type or "movie"

    for source, ext_id in (("imdb_id", imdb_id), ("tvdb_id", tvdb_id)):
        if not ext_id:
            continue
        data = await _get(client, f"/find/{ext_id}", {"external_source": source})
        if not data:
            continue
        movie_results = data.get("movie_results") or []
        tv_results = data.get("tv_results") or []
        if media_type == "tv" and tv_results:
            return str(tv_results[0]["id"]), "tv"
        if media_type == "movie" and movie_results:
            return str(movie_results[0]["id"]), "movie"
        # No media_type hint (or it didn't match) — take whichever came back.
        if movie_results:
            return str(movie_results[0]["id"]), "movie"
        if tv_results:
            return str(tv_results[0]["id"]), "tv"
    return None


async def get_images(client: httpx.AsyncClient, media_type: str, tmdb_id: str) -> dict[str, list[dict]]:
    """Raw TMDB /images response: {"posters": [...], "backdrops": [...], "logos": [...]}.
    Every entry is unfiltered by language — filtering happens in the resolver.
    """
    data = await _get(client, f"/{_endpoint(media_type)}/{tmdb_id}/images", {"include_image_language": "en,null,%2A"})
    if not data:
        return {"posters": [], "backdrops": [], "logos": []}
    return {
        "posters": data.get("posters", []),
        "backdrops": data.get("backdrops", []),
        "logos": data.get("logos", []),
    }


async def get_details(client: httpx.AsyncClient, media_type: str, tmdb_id: str) -> dict[str, Any] | None:
    """Details + credits + keywords + external_ids in one call, used both for
    the "primary art" last-resort fallback and as input to the sash engine.
    """
    append = "credits,keywords,external_ids"
    data = await _get(client, f"/{_endpoint(media_type)}/{tmdb_id}", {"append_to_response": append})
    if not data:
        return None
    # keywords come back under "keywords" for movies (list) or "results" (tv)
    kw_block = data.get("keywords") or {}
    data["_keyword_list"] = kw_block.get("keywords") or kw_block.get("results") or []
    return data


async def get_release_dates(client: httpx.AsyncClient, tmdb_id: str) -> dict | None:
    """Raw TMDB /movie/{id}/release_dates payload (theatrical/digital/physical
    dates per region), used by app.sash.release_status."""
    return await _get(client, f"/movie/{tmdb_id}/release_dates")


async def trending(client: httpx.AsyncClient, media_type: str) -> list[str]:
    """Ordered list of TMDB ids from TMDB's own daily trending endpoint."""
    kind = "tv" if media_type == "tv" else "movie"
    data = await _get(client, f"/trending/{kind}/day")
    if not data:
        return []
    return [str(item["id"]) for item in (data.get("results") or []) if item.get("id") is not None]
