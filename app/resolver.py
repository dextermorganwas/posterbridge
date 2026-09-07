# app/resolver.py
#
# The fallback chain for poster/backdrop/logo art:
#
#   1. TMDB, English
#   2. TMDB, original language (skipped if the original language IS English)
#   3. Metahub (imdb-keyed; poster/backdrop only — Metahub has no logo art)
#   4. TVDB, English
#   5. TVDB, original language
#   6. TMDB primary art for the title, regardless of language
#   7. TVDB primary art for the title, regardless of language
#
# Backdrops are restricted to textless art at every TMDB/TVDB step (an
# untagged/"null"-language image on both providers is their textless
# convention). Posters and logos use the language-based steps above as-is.
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from app.identifiers import MediaIds
from app.sources import tmdb as tmdb_src
from app.sources import tvdb as tvdb_src
from app.sources import metahub as metahub_src
from app.config import TMDB_POSTER_SIZE, TMDB_BACKDROP_SIZE, TMDB_LOGO_SIZE

logger = logging.getLogger(__name__)

ArtKind = Literal["poster", "backdrop", "logo"]

_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"


@dataclass
class ResolvedArt:
    url: str | None
    source: str  # "tmdb_en" | "tmdb_orig" | "metahub" | "tvdb_en" | "tvdb_orig" | "tmdb_primary" | "tvdb_primary" | "none"
    tmdb_id: str | None = None
    media_type: str | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    original_language: str | None = None
    details: dict | None = None  # full TMDB details, reused by the sash engine


def _tmdb_size_for(kind: ArtKind) -> str:
    return {"poster": TMDB_POSTER_SIZE, "backdrop": TMDB_BACKDROP_SIZE, "logo": TMDB_LOGO_SIZE}[kind]


def _tmdb_full_url(file_path: str, kind: ArtKind) -> str:
    return f"{_TMDB_IMAGE_BASE}/{_tmdb_size_for(kind)}{file_path}"


def _tmdb_pool(images: dict, kind: ArtKind) -> list[dict]:
    key = {"poster": "posters", "backdrop": "backdrops", "logo": "logos"}[kind]
    items = images.get(key, [])
    if kind == "backdrop":
        items = [im for im in items if not im.get("iso_639_1")]  # textless only
    return items


def _pick_by_language(items: list[dict], lang: str | None) -> dict | None:
    matches = [im for im in items if im.get("iso_639_1") == lang]
    if not matches:
        return None
    matches.sort(key=lambda im: (im.get("vote_average") or 0, im.get("vote_count") or 0), reverse=True)
    return matches[0]


def _pick_best(items: list[dict]) -> dict | None:
    if not items:
        return None
    ranked = sorted(items, key=lambda im: (im.get("vote_average") or 0, im.get("vote_count") or 0), reverse=True)
    return ranked[0]


async def resolve(
    client: httpx.AsyncClient, ids: MediaIds, kind: ArtKind
) -> ResolvedArt:
    resolved = await tmdb_src.resolve_tmdb_id(
        client,
        tmdb_id=ids.tmdb_id,
        imdb_id=ids.imdb_id,
        tvdb_id=ids.tvdb_id,
        media_type=ids.media_type,
    )
    if not resolved:
        return ResolvedArt(url=None, source="none")
    tmdb_id, media_type = resolved

    details = await tmdb_src.get_details(client, media_type, tmdb_id)
    imdb_id = ids.imdb_id or ((details or {}).get("external_ids") or {}).get("imdb_id")
    tvdb_hint = ids.tvdb_id or ((details or {}).get("external_ids") or {}).get("tvdb_id")
    original_language = (details or {}).get("original_language")

    result = ResolvedArt(
        url=None, source="none", tmdb_id=tmdb_id, media_type=media_type,
        imdb_id=imdb_id, original_language=original_language, details=details,
    )

    # --- 1/2: TMDB english, then original language (unless orig == en) ---
    images = await tmdb_src.get_images(client, media_type, tmdb_id)
    pool = _tmdb_pool(images, kind)

    en_pick = _pick_by_language(pool, "en") if kind != "backdrop" else _pick_best(pool)
    if kind == "backdrop":
        # Backdrops are language-agnostic (textless is the only filter) —
        # rank straight from the textless pool.
        if en_pick and en_pick.get("file_path"):
            result.url = _tmdb_full_url(en_pick["file_path"], kind)
            result.source = "tmdb_en"
            return result
    else:
        if en_pick and en_pick.get("file_path"):
            result.url = _tmdb_full_url(en_pick["file_path"], kind)
            result.source = "tmdb_en"
            return result
        if original_language and original_language != "en":
            orig_pick = _pick_by_language(pool, original_language)
            if orig_pick and orig_pick.get("file_path"):
                result.url = _tmdb_full_url(orig_pick["file_path"], kind)
                result.source = "tmdb_orig"
                return result

    # --- 3: Metahub (poster/backdrop only) ---
    if kind == "poster":
        url = await metahub_src.resolve_poster(client, imdb_id)
        if url:
            result.url, result.source = url, "metahub"
            return result
    elif kind == "backdrop":
        url = await metahub_src.resolve_backdrop(client, imdb_id)
        if url:
            result.url, result.source = url, "metahub"
            return result

    # --- 4/5: TVDB english, then original language ---
    tvdb_id = await tvdb_src.resolve_tvdb_id(
        client, media_type=media_type, tvdb_id_hint=tvdb_hint, imdb_id=imdb_id, tmdb_id=tmdb_id
    )
    if tvdb_id:
        result.tvdb_id = tvdb_id
        artworks = await tvdb_src.fetch_artworks(client, tvdb_id, media_type)
        tvdb_key = {"poster": "posters", "backdrop": "backgrounds", "logo": "logos"}[kind]
        tvdb_items = artworks.get(tvdb_key, [])

        if kind == "backdrop":
            pick = tvdb_src.select_textless(tvdb_items, None)
            if pick:
                result.url, result.source = pick["url"], "tvdb_en"
                return result
        else:
            strict = kind == "logo"
            en_pick = tvdb_src.select_by_language(tvdb_items, ["eng"], strict=strict)
            if en_pick:
                result.url, result.source = en_pick["url"], "tvdb_en"
                return result
            if original_language and original_language != "en":
                orig_pick = tvdb_src.select_by_language(
                    tvdb_items, [_lang2_to_tvdb(original_language)], strict=strict
                )
                if orig_pick:
                    result.url, result.source = orig_pick["url"], "tvdb_orig"
                    return result

    # --- 6: TMDB primary art, any language ---
    # "Whatever TMDB gives as primary" means its own poster_path/backdrop_path
    # field (the one designated in the title's own /details response), not a
    # re-derived "best of all languages" pick — those usually coincide, but
    # the literal field is what was asked for. Logos have no such single
    # field on TMDB, so logo still falls back to the best-voted item across
    # all languages in the images list.
    if kind == "poster" and (details or {}).get("poster_path"):
        result.url, result.source = _tmdb_full_url(details["poster_path"], "poster"), "tmdb_primary"
        return result
    if kind == "logo":
        primary_pick = _pick_best(images.get("logos", []))
        if primary_pick and primary_pick.get("file_path"):
            result.url, result.source = _tmdb_full_url(primary_pick["file_path"], "logo"), "tmdb_primary"
            return result
    if kind == "backdrop":
        # Textless pool only (already filtered) — no un-tagged fallback here:
        # details["backdrop_path"] isn't guaranteed textless, and backdrops
        # are textless-only at every tier per spec.
        primary_pick = _pick_best(pool)
        if primary_pick and primary_pick.get("file_path"):
            result.url, result.source = _tmdb_full_url(primary_pick["file_path"], "backdrop"), "tmdb_primary"
            return result

    # --- 7: TVDB primary art, any language (backdrops stay textless-only) ---
    if result.tvdb_id:
        artworks = await tvdb_src.fetch_artworks(client, result.tvdb_id, media_type)
        tvdb_key = {"poster": "posters", "backdrop": "backgrounds", "logo": "logos"}[kind]
        items = artworks.get(tvdb_key, [])
        if kind == "backdrop":
            pick = tvdb_src.select_textless(items, None)
            if pick:
                result.url, result.source = pick["url"], "tvdb_primary"
                return result
        elif items:
            result.url, result.source = items[0]["url"], "tvdb_primary"
            return result

    return result


_LANG_2_TO_3 = {
    "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita",
    "pt": "por", "ja": "jpn", "ko": "kor", "zh": "zho", "ru": "rus",
    "nl": "nld", "pl": "pol", "sv": "swe", "da": "dan", "no": "nor",
    "fi": "fin", "tr": "tur", "ar": "ara", "hi": "hin", "cs": "ces",
    "hu": "hun", "el": "ell", "he": "heb", "th": "tha", "uk": "ukr",
    "ro": "ron",
}


def _lang2_to_tvdb(code: str | None) -> str | None:
    if not code:
        return code
    return _LANG_2_TO_3.get(code.strip().lower(), code)
