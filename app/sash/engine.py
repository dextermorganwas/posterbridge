# app/sash/engine.py
#
# Wires PostersPlus's ported sash-selection logic (app/sash/discovery.py's
# extract_discovery_meta/_evaluate_slot, app/sash/awards_data.py's
# parse_mdblist_awards, app/sash/festivals.py) together with PosterBridge's
# own signals — the IMDb-dataset "top_rated" slot and a TMDB-status-derived
# release_status — to pick a single sash label for a title.
from __future__ import annotations

import logging

import httpx

from app.config import SASH_PRIORITY, SASH_PRIORITY_RAW, TOP_RATED_MIN_SCORE, DIGITAL_RELEASE_ENABLED
from app.sash import discovery as disc
from app.sash import imdb_dataset
from app.sash import release_status as release_status_src
from app.sash.awards_data import parse_mdblist_awards
from app.sash.festivals import match_festival_keyword
from app.sources import mdblist as mdblist_src
from app.trending import trending_rank

logger = logging.getLogger(__name__)


def parse_priority(raw: str | None) -> list[str]:
    if not raw:
        return list(SASH_PRIORITY)
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    return tokens or list(SASH_PRIORITY)


async def _compute_release_status(
    client: httpx.AsyncClient, details: dict, media_type: str, tmdb_id: str, imdb_id: str | None
) -> str | None:
    """Cinema/Streaming/Physical/Production (movies) or Airing/Ended/
    Cancelled (TV) — see app/sash/release_status.py (TMDB /release_dates
    based, adapted from PostersPlus). If DIGITAL_RELEASE_ENABLED, a movie
    still showing Cinema/Production is upgraded to Streaming when
    app/sash/digital_release.py's r/movieleaks-derived signal has already
    seen it announced, ahead of TMDB publishing an official digital date."""
    status = await release_status_src.fetch_release_status(
        client, media_type, tmdb_id, details.get("status")
    )
    if (
        DIGITAL_RELEASE_ENABLED
        and media_type == "movie"
        and status in ("Cinema", "Production")
        and imdb_id
    ):
        from app.cache import is_digital_release
        if is_digital_release(imdb_id):
            return "Streaming"
    return status


async def pick_sash_label(
    client: httpx.AsyncClient,
    *,
    details: dict,
    media_type: str,
    tmdb_id: str,
    imdb_id: str | None,
    priority_raw: str | None = None,
) -> tuple[str, str] | None:
    """Returns (label, sash_type) or None."""
    priority = parse_priority(priority_raw or SASH_PRIORITY_RAW)

    keywords = details.get("_keyword_list") or []
    mdb_keywords = await mdblist_src.fetch_keywords(client, media_type, tmdb_id) if mdblist_src.enabled() else []
    all_keywords = keywords + mdb_keywords
    keyword_names = {(kw.get("name") or "").lower().strip() for kw in all_keywords}

    wins, noms = parse_mdblist_awards(mdb_keywords, tmdb_id)

    rank = await trending_rank(client, media_type, tmdb_id)
    release_status = await _compute_release_status(client, details, media_type, tmdb_id, imdb_id)

    meta = disc.extract_discovery_meta(
        details,
        media_type,
        wins,
        noms,
        rank,
        tmdb_id=tmdb_id,
        release_date=details.get("release_date") or details.get("first_air_date"),
        keywords=all_keywords,
        festival_keyword=match_festival_keyword(keyword_names),
        release_status_override=release_status,
    )

    # top_rated is new to PosterBridge (IMDb dataset), so it's evaluated
    # ahead of delegating the rest of the list to discovery._evaluate_slot.
    for slot in priority:
        if slot == "top_rated":
            score = imdb_dataset.get_rating(imdb_id)
            if score is not None and score >= TOP_RATED_MIN_SCORE:
                return "Top Rated", "win"
            continue
        label = disc._evaluate_slot(slot, meta)
        if label is not None:
            sash_type = disc._SASH_TYPES.get(slot, "info")
            return label, sash_type

    return None
