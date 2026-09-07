# Third-party notices

PosterBridge is licensed under the **GNU Affero General Public License v3.0**
(see `LICENSE`) because it incorporates adapted code from
[PostersPlus](https://github.com/UmbraProjects/PostersPlus), which is also
AGPLv3-licensed.

## Files adapted from PostersPlus

- `app/sash/awards_data.py` — Golden Globe / Emmy curated TMDB-id sets, the
  MDBList award-keyword parser (`parse_mdblist_awards`), and the
  dominant-colour clustering algorithm (`_dominant_cluster`,
  `dominant_frost_rgb`, `_frost_ink`, `_frosted_tint`). PostersPlus's poster
  overlay drawing code was removed — PosterBridge draws its own sash shape
  in `app/sash/render.py`.
- `app/sash/festivals.py` — festival keyword matching and top-prize TMDB-id
  sets (Cannes, Venice, Berlin, Locarno, Sundance). Copied unchanged.
- `app/sash/discovery.py` — the curated notable-studio/director/cast lists,
  the "one interesting thing" priority-slot evaluator
  (`extract_discovery_meta`, `pick_sash`, `_evaluate_slot`), and the
  operator-override loader for `discovery_overrides.json`. Copied with only
  import-path changes.
- `app/sash/imdb_dataset.py` — the IMDb `title.ratings.tsv.gz` dataset
  downloader/refresher and rating lookup. Copied with only import-path
  changes.
- `app/sash/release_status.py` — the date-based Cinema/Streaming/Physical
  status computation (`_compute_movie_status_from_dates`) and the tiered
  cache-TTL scheme (`release_status_expiry`). Adapted to PosterBridge's
  sqlite selection cache instead of PostersPlus's dedicated tables.
- `app/sash/digital_release.py` — the r/movieleaks-via-Arctic-Shift early
  digital-release poller. Copied with only the storage call changed.
- `app/config.py`'s `effective_cpus()` function (cgroup-aware CPU-limit
  detection). Copied unchanged.

## Files newly written for PosterBridge (not derived from PostersPlus)

Everything else — the AIOMetadata URL parsing (`app/identifiers.py`), the
TMDB/TVDB/Metahub fallback-chain resolver (`app/resolver.py`,
`app/sources/`), the sash shape/rendering (`app/sash/render.py`,
`app/sash/color.py`'s blend-to-fill logic), the sash-selection wiring
(`app/sash/engine.py`), request coalescing and the sqlite cache
(`app/cache.py`), and the FastAPI app/deployment tooling (`app/main.py`,
`Dockerfile`, `docker-compose.yml`, GitHub Actions workflow).

## AGPLv3 obligation

Because this project links against AGPLv3-licensed code, **the whole
PosterBridge project is AGPLv3**, including the parts listed as "newly
written" above. If you deploy this (including privately, for personal use,
since Stremio clients connecting to it over your LAN/internet count as
"users interacting with it over a network" under AGPLv3 §13), you must make
this project's complete corresponding source available to anyone who uses
it. Keeping your fork's source on a public GitHub repo — which this
project's own GHCR publishing setup already points at — satisfies that.
