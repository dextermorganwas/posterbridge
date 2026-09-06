# app/sources/tvdb.py
#
# TheTVDB v4 client. The login/token flow, the dynamic artwork-type
# discovery via /artwork/types (classifying by slug/name keyword rather than
# hardcoded numeric ids, so a TVDB renumbering can't break this), the
# /search/remoteid id resolution, and the language-selection fallback order
# are adapted from PostersPlus (AGPLv3) tvdb.py — see /NOTICE.md.
from __future__ import annotations

import asyncio
import logging

import httpx

from app.cache import get_selection, set_selection
from app.config import TVDB_API_KEY, TVDB_SUBSCRIBER_PIN, HTTP_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_API_BASE = "https://api4.thetvdb.com/v4"
_ARTWORK_BASE = "https://artworks.thetvdb.com"

_token_mem: str | None = None
_login_lock = asyncio.Lock()

_TYPES_CACHE_TTL = 30 * 86400
_ARTWORK_CACHE_TTL = 7 * 86400
_ID_CACHE_TTL = 7 * 86400
_NEG_CACHE_TTL = 3 * 86400


def enabled() -> bool:
    return bool(TVDB_API_KEY)


async def _login(client: httpx.AsyncClient) -> str | None:
    payload = {"apikey": TVDB_API_KEY}
    if TVDB_SUBSCRIBER_PIN:
        payload["pin"] = TVDB_SUBSCRIBER_PIN
    try:
        resp = await client.post(f"{_API_BASE}/login", json=payload, timeout=15.0)
        resp.raise_for_status()
        return ((resp.json() or {}).get("data") or {}).get("token")
    except httpx.HTTPError as exc:
        logger.warning(f"TVDB login failed: {exc}")
        return None


async def _get_token(client: httpx.AsyncClient, *, force: bool = False) -> str | None:
    global _token_mem
    if not force and _token_mem:
        return _token_mem
    async with _login_lock:
        if not force and _token_mem:
            return _token_mem
        _token_mem = await _login(client)
        return _token_mem


async def _authed_get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict | list | None:
    global _token_mem
    token = await _get_token(client)
    if not token:
        return None
    for attempt in (1, 2):
        try:
            resp = await client.get(
                f"{_API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            if resp.status_code == 401 and attempt == 1:
                _token_mem = None
                token = await _get_token(client, force=True)
                if not token:
                    return None
                continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return (resp.json() or {}).get("data")
        except httpx.HTTPError as exc:
            logger.warning(f"TVDB GET {path} failed: {exc}")
            return None
    return None


def _classify(slug: str, name: str) -> str | None:
    text = f"{slug} {name}".lower()
    if "clearlogo" in text or text.strip().endswith("logo") or " logo" in text:
        return "logos"
    if "background" in text or "fanart" in text:
        return "backgrounds"
    if "poster" in text:
        return "posters"
    return None


async def _type_map(client: httpx.AsyncClient) -> dict[str, dict[int, str]]:
    cached = get_selection("tvdb:artwork_types")
    if cached:
        return {rt: {int(k): v for k, v in inner.items()} for rt, inner in cached.items()}
    data = await _authed_get(client, "/artwork/types")
    out: dict[str, dict[int, str]] = {"movie": {}, "series": {}}
    if isinstance(data, list):
        for t in data:
            rt = (t.get("recordType") or "").lower()
            cat = _classify(t.get("slug") or "", t.get("name") or "")
            tid = t.get("id")
            if rt in out and cat and isinstance(tid, int):
                out[rt][tid] = cat
    if out["movie"] or out["series"]:
        set_selection(
            "tvdb:artwork_types",
            {rt: {str(k): v for k, v in inner.items()} for rt, inner in out.items()},
            _TYPES_CACHE_TTL,
        )
    return out


def _record_type(media_type: str) -> str:
    return "series" if media_type in ("tv", "series") else "movie"


async def resolve_tvdb_id(
    client: httpx.AsyncClient,
    *,
    media_type: str,
    tvdb_id_hint: str | int | None = None,
    imdb_id: str | None = None,
    tmdb_id: str | None = None,
) -> int | None:
    if not enabled():
        return None
    if tvdb_id_hint:
        try:
            return int(tvdb_id_hint)
        except (TypeError, ValueError):
            pass

    want = _record_type(media_type)
    cache_key = f"tvdb:id:{want}:{imdb_id or ''}:{tmdb_id or ''}"
    cached = get_selection(cache_key)
    if cached is not None:
        return cached.get("tvdb_id")

    resolved: int | None = None
    for remote in (imdb_id, tmdb_id):
        if not remote:
            continue
        data = await _authed_get(client, f"/search/remoteid/{remote}")
        if not isinstance(data, list):
            continue
        for item in data:
            rec = item.get(want) if isinstance(item, dict) else None
            if isinstance(rec, dict) and rec.get("id"):
                try:
                    resolved = int(rec["id"])
                except (TypeError, ValueError):
                    resolved = None
                break
        if resolved is not None:
            break

    set_selection(cache_key, {"tvdb_id": resolved}, _ID_CACHE_TTL if resolved else _NEG_CACHE_TTL)
    return resolved


async def fetch_artworks(client: httpx.AsyncClient, tvdb_id: int, media_type: str) -> dict[str, list[dict]]:
    """{'logos': [...], 'backgrounds': [...], 'posters': [...]}, each item
    {'url', 'language', 'score'}, sorted by descending score."""
    if not enabled():
        return {"logos": [], "backgrounds": [], "posters": []}

    want = _record_type(media_type)
    cache_key = f"tvdb:art:{want}:{tvdb_id}"
    cached = get_selection(cache_key)
    if cached is not None:
        return cached

    out: dict[str, list[dict]] = {"logos": [], "backgrounds": [], "posters": []}
    type_map = await _type_map(client)
    endpoint = "series" if want == "series" else "movies"
    data = await _authed_get(client, f"/{endpoint}/{tvdb_id}/extended", params={"short": "false"})
    artworks = (data or {}).get("artworks") if isinstance(data, dict) else None
    if isinstance(artworks, list):
        id_to_cat = type_map.get(want, {})
        for art in artworks:
            cat = id_to_cat.get(art.get("type"))
            if not cat:
                continue
            image = art.get("image") or ""
            if not image:
                continue
            url = image if image.startswith("http") else f"{_ARTWORK_BASE}/{image.lstrip('/')}"
            out[cat].append({
                "url": url,
                "language": art.get("language"),
                "score": float(art.get("score") or 0),
            })
        for cat in out:
            out[cat].sort(key=lambda a: a["score"], reverse=True)

    set_selection(cache_key, out, _ARTWORK_CACHE_TTL if any(out.values()) else _NEG_CACHE_TTL)
    return out


def select_by_language(items: list[dict], languages: list[str] | None, *, strict: bool = False) -> dict | None:
    """Pick the best item by language preference, then neutral, then English.
    strict=True (logos) skips the "just take anything" last resort."""
    if not items:
        return None
    for language in languages or ():
        if not language:
            continue
        for it in items:
            if it.get("language") == language:
                return it
    for it in items:
        if it.get("language") in (None, ""):
            return it
    for it in items:
        if it.get("language") == "eng":
            return it
    return None if strict else items[0]


def select_textless(items: list[dict], languages: list[str] | None) -> dict | None:
    """Backdrops: language-neutral entries are TVDB's textless art."""
    neutral = [it for it in items if it.get("language") in (None, "")]
    return select_by_language(neutral, languages) if neutral else None
