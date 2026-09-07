# app/main.py
#
# FastAPI app exposing the AIOMetadata-compatible art endpoints:
#   GET /poster/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
#   GET /backdrop/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
#   GET /logo/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
#
# Concurrent requests for the same title+kind are coalesced into a single
# upstream resolution/render (app/cache.coalesced). Shutdown drains
# in-flight requests, cancels the background IMDb-dataset refresh loop, and
# closes the shared HTTP client and sqlite connections (see lifespan below
# and entrypoint.sh's SIGTERM handling).
from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from PIL import Image

from app import cache
from app.config import (
    HTTP_TIMEOUT_SECONDS,
    UPSTREAM_CONCURRENCY,
    RENDER_WORKERS,
    SELECTION_CACHE_TTL_HOURS,
    NEGATIVE_CACHE_TTL_HOURS,
    HTTP_CACHE_MAX_AGE_SECONDS,
    SASH_ENABLED,
    GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    DIGITAL_RELEASE_ENABLED,
    LOG_LEVEL,
)
from app.identifiers import parse_ids
from app.resolver import resolve, ArtKind
from app.sash import imdb_dataset
from app.sash.digital_release import digital_release_poll_loop
from app.sash.engine import pick_sash_label
from app.sash.render import draw_sash

logging.basicConfig(level=LOG_LEVEL.upper())
logger = logging.getLogger("posterbridge")

_render_pool = ThreadPoolExecutor(max_workers=RENDER_WORKERS, thread_name_prefix="render")
_background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_connections=UPSTREAM_CONCURRENCY, max_keepalive_connections=UPSTREAM_CONCURRENCY)
    app.state.client = httpx.AsyncClient(limits=limits, timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)

    imdb_dataset.init_db()
    task = asyncio.create_task(imdb_dataset.imdb_dataset_refresh_loop(app.state.client))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    if DIGITAL_RELEASE_ENABLED:
        dr_task = asyncio.create_task(digital_release_poll_loop(app.state.client))
        _background_tasks.add(dr_task)
        dr_task.add_done_callback(_background_tasks.discard)

    logger.info("PosterBridge started")
    try:
        yield
    finally:
        logger.info("Shutting down: cancelling background tasks")
        for t in list(_background_tasks):
            t.cancel()
        if _background_tasks:
            await asyncio.wait(_background_tasks, timeout=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS)

        await app.state.client.aclose()
        _render_pool.shutdown(wait=True, cancel_futures=False)
        cache.close_all()
        logger.info("Shutdown complete")


app = FastAPI(title="PosterBridge", lifespan=lifespan)


def _client(request: Request) -> httpx.AsyncClient:
    return request.app.state.client


async def _download(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError as exc:
        logger.warning(f"Download failed for {url}: {exc}")
        return None


def _render_sash_sync(image_bytes: bytes, label: str) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    composed = draw_sash(image, label)
    out = io.BytesIO()
    composed.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


async def _build_response(
    client: httpx.AsyncClient, kind: ArtKind, raw_path: str, sash_priority: str | None
) -> Response:
    ids = parse_ids(raw_path)
    if ids.is_empty():
        raise HTTPException(status_code=404, detail="No usable id in request")

    cache_key = f"render:{kind}:{ids.cache_key()}:{sash_priority or ''}"
    cached = cache.get_selection(cache_key)
    if cached and cached.get("miss"):
        raise HTTPException(status_code=404, detail="No art found")

    async def compute() -> dict:
        art = await resolve(client, ids, kind)
        if not art.url:
            cache.set_selection(cache_key, {"miss": True}, NEGATIVE_CACHE_TTL_HOURS * 3600)
            return {"miss": True}

        image_bytes = await _download(client, art.url)
        if image_bytes is None:
            cache.set_selection(cache_key, {"miss": True}, NEGATIVE_CACHE_TTL_HOURS * 3600)
            return {"miss": True}

        label = None
        if SASH_ENABLED and kind == "poster" and art.details:
            pick = await pick_sash_label(
                client,
                details=art.details,
                media_type=art.media_type or "movie",
                tmdb_id=art.tmdb_id or "",
                imdb_id=art.imdb_id,
                priority_raw=sash_priority,
            )
            label = pick[0] if pick else None

        if label:
            loop = asyncio.get_running_loop()
            final_bytes = await loop.run_in_executor(_render_pool, _render_sash_sync, image_bytes, label)
            content_type = "image/jpeg"
        else:
            final_bytes = image_bytes
            content_type = "image/jpeg" if art.url.lower().endswith((".jpg", ".jpeg")) else "image/png"

        payload = {"miss": False, "content_type": content_type, "data": base64.b64encode(final_bytes).decode("ascii")}
        cache.set_selection(cache_key, payload, SELECTION_CACHE_TTL_HOURS * 3600)
        return payload

    result = cached or await cache.coalesced(cache_key, compute)
    if result.get("miss"):
        raise HTTPException(status_code=404, detail="No art found")

    data = base64.b64decode(result["data"])
    return Response(
        content=data,
        media_type=result["content_type"],
        headers={"Cache-Control": f"public, max-age={HTTP_CACHE_MAX_AGE_SECONDS}"},
    )


@app.get("/poster/{raw_path:path}")
async def get_poster(raw_path: str, request: Request, sash_priority: str | None = None):
    return await _build_response(_client(request), "poster", raw_path, sash_priority)


@app.get("/backdrop/{raw_path:path}")
async def get_backdrop(raw_path: str, request: Request, sash_priority: str | None = None):
    return await _build_response(_client(request), "backdrop", raw_path, sash_priority)


@app.get("/logo/{raw_path:path}")
async def get_logo(raw_path: str, request: Request):
    return await _build_response(_client(request), "logo", raw_path, None)


@app.get("/health")
async def health():
    return {"status": "ok", "imdb_dataset": imdb_dataset.status(), "time": time.time()}


@app.get("/stats")
async def stats(access_key: str | None = None):
    from app.config import ACCESS_KEY
    if ACCESS_KEY and access_key != ACCESS_KEY:
        raise HTTPException(status_code=403, detail="Invalid access_key")
    return {
        "imdb_dataset": imdb_dataset.status(),
        "expired_selections_pruned_last_call": cache.prune_expired(),
    }
