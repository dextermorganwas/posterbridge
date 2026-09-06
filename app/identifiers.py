# app/identifiers.py
#
# Parses AIOMetadata-style custom art URL paths:
#   tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
#
# Any id segment may be blank (AIOMetadata sends the segment with an empty
# value, e.g. "imdb:", when it has no id to fill the "?" placeholder for).
# Segment order is not assumed — each is matched by its "tmdb"/"imdb"/"tvdb"
# prefix regardless of position.
from __future__ import annotations

import re
from dataclasses import dataclass

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_SEGMENT_RE = re.compile(r"^(tmdb|imdb|tvdb):(.*)$", re.IGNORECASE)

_TYPE_MOVIE = {"movie", "movies", "film"}
_TYPE_TV = {"tv", "series", "show", "shows"}


@dataclass
class MediaIds:
    media_type: str | None = None  # "movie" | "tv"
    tmdb_id: str | None = None
    imdb_id: str | None = None
    tvdb_id: str | None = None

    def cache_key(self) -> str:
        return f"{self.media_type or '?'}:{self.tmdb_id or ''}:{self.imdb_id or ''}:{self.tvdb_id or ''}"

    def is_empty(self) -> bool:
        return not any((self.tmdb_id, self.imdb_id, self.tvdb_id))


def _normalise_type(raw: str) -> str | None:
    t = raw.strip().lower()
    if t in _TYPE_TV:
        return "tv"
    if t in _TYPE_MOVIE:
        return "movie"
    return None


def _strip_extension(raw: str) -> str:
    lowered = raw.lower()
    for ext in _IMAGE_EXTENSIONS:
        if lowered.endswith(ext):
            return raw[: -len(ext)]
    return raw


def parse_ids(raw_path: str) -> MediaIds:
    """Parse a path like ``tmdb:movie:603&imdb:tt0133093&tvdb:.jpg`` into
    a MediaIds. Unknown/malformed segments are ignored rather than raising,
    so a partially-populated AIOMetadata URL still resolves whatever ids it
    does carry.
    """
    body = _strip_extension(raw_path.strip())
    ids = MediaIds()
    for segment in body.split("&"):
        segment = segment.strip()
        if not segment:
            continue
        match = _SEGMENT_RE.match(segment)
        if not match:
            continue
        source, rest = match.group(1).lower(), match.group(2)
        if source == "tmdb":
            parts = rest.split(":", 1)
            if len(parts) == 2:
                media_type, tmdb_id = parts
                ids.media_type = _normalise_type(media_type)
                ids.tmdb_id = tmdb_id.strip() or None
            elif len(parts) == 1 and parts[0].strip():
                ids.tmdb_id = parts[0].strip()
        elif source == "imdb":
            ids.imdb_id = rest.strip() or None
        elif source == "tvdb":
            ids.tvdb_id = rest.strip() or None
    return ids
