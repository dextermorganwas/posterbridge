# app/sash/engine.py
#
# Wires PostersPlus's ported sash-selection logic (app/sash/discovery.py's
# extract_discovery_meta/_evaluate_slot, app/sash/awards_data.py's
# parse_mdblist_awards, app/sash/festivals.py) together with PosterBridge's
# own signals — the IMDb-dataset "top_rated" slot and a TMDB-status-derived
# release_status — to pick a single sash label for a title.
from __future__ import annotations

import datetime as _dt
import logging

import httpx

from app.config import SASH_PRIORITY, SASH_PRIORITY_RAW, TOP_RATED_MIN_SCORE
from app.sash import discovery as disc
from app.sash import imdb_dataset
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


def _compute_release_status(details: dict, media_type: str) -> str | None:
    """Best-effort release_status label from TMDB's own status field —
    PostersPlus's finer physical/streaming split relies on a digital-release
    tracker this project doesn't include, so a released movie is bucketed by
    how recently it opened instead."""
    status = (details or {}).get("status") or ""
    if media_type == "tv":
        return {
            "Returning Series": "Airing",
            "Ended": "Ended",
            "Canceled": "Cancelled",
            "Cancelled": "Cancelled",
            "In Production": "Production",
            "Planned": "Production",
        }.get(status)

    if status in ("In Production", "Post Production", "Planned"):
        return "Production"
    if status == "Released":
        release_date = details.get("release_date")
        if release_date:
            try:
                d = _dt.date.fromisoformat(release_date)
                if (_dt.date.today() - d).days <= 45:
                    return "Cinema"
            except ValueError:
                pass
        return "Streaming"
    return None


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
        release_status_override=_compute_release_status(details, media_type),
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
