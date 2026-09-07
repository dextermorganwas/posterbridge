# PosterBridge

A self-hosted artwork server for Stremio (via the [AIOMetadata](https://github.com/cedya77/aiometadata)
add-on) or any similar client that supports custom poster/backdrop/logo URLs.
It resolves the best available art across TMDB, TVDB and Metahub, and can
overlay a single "sash" badge (Trending, Top Rated, Golden Globe Winner,
Airing, etc.) whose colour is picked from the art's own dominant colour.

Licensed **AGPLv3** — see `LICENSE` and `NOTICE.md` for why (short version:
it incorporates adapted code from [PostersPlus](https://github.com/UmbraProjects/PostersPlus)).

## What it does

- **Art resolution** (`/poster`, `/backdrop`, `/logo`): TMDB English → TMDB
  original language → Metahub → TVDB English → TVDB original language →
  TMDB's primary art → TVDB's primary art. Backdrops are textless-only at
  every step.
- **Sash overlay**: a thin line near the bottom of the poster/backdrop with
  a tab that curves up to hold a label — colour picked from the art's
  dominant colour (clean dark grey on dark/black posters). Priority order
  (which single sash wins when several could apply) is fully configurable
  — see `SASH_PRIORITY` in `.env.example`.
- **Top Rated sash**: sourced from IMDb's own `title.ratings.tsv.gz`
  dataset, refreshed daily, defaulting to a 8.5+/10 (i.e. "85+/100") cutoff.
- **Trending sash**: TMDB's daily trending endpoint by default, or point it
  at a public MDBList list URL — no MDBList API key required for that.
- Concurrent requests for the same title are coalesced into one upstream
  fetch; results are cached (see `.env.example` for TTLs).
- Graceful shutdown: `docker stop`/`compose down` drain in-flight requests
  and cleanly close the HTTP client and background refresh task.

## Configuring AIOMetadata

In AIOMetadata's custom art URL settings, use (replacing the host with
wherever you deploy this):

```
Poster:   http://YOUR_SERVER:8000/poster/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
Backdrop: http://YOUR_SERVER:8000/backdrop/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
Logo:     http://YOUR_SERVER:8000/logo/tmdb:{type}:{tmdb_id?}&imdb:{imdb_id?}&tvdb:{tvdb_id?}.jpg
```

## Configuration

All settings live in `.env` (copy `.env.example` and fill it in). Every
setting is documented there — API keys, image sizes, cache TTLs, resource
limits, IMDb dataset behaviour, trending source, and sash priority/styling.

---

## Deploying — complete walkthrough (GitHub Desktop → GHCR → Docker)

This assumes no git experience. GitHub Desktop is a fine choice here — you
won't need the command line for the GitHub half at all.

### Part 1 — Create the GitHub repository

1. Go to **github.com**, sign in (create a free account if you don't have
   one).
2. Click the **+** in the top-right corner → **New repository**.
3. Name it `posterbridge` (or anything you like — just remember it, you'll
   need it later for the image name).
4. Set it to **Public**. This matters for two reasons: it satisfies the
   AGPLv3 source-availability requirement this project carries (see
   `NOTICE.md`), and it means your Docker server can later `docker pull`
   the built image without logging in to GHCR at all.
5. Tick **Add a README file** (doesn't matter what's in it — makes the
   next step simpler).
6. Click **Create repository**.

### Part 2 — Clone it with GitHub Desktop

1. Open **GitHub Desktop**. If this is the first time, it'll ask you to
   sign in with your GitHub account — do that.
2. **File → Clone repository**.
3. Switch to the **GitHub.com** tab in that dialog — your new `posterbridge`
   repo should be listed. Select it.
4. Pick a **Local path** (e.g. `C:\Users\you\Documents\posterbridge`) — this
   is the folder GitHub Desktop will keep in sync with GitHub.
5. Click **Clone**.

### Part 3 — Add the project files

1. Download the `posterbridge` project files I've provided (see the
   attached file in this conversation) and extract the zip.
2. Copy **everything inside** the extracted folder into the local folder
   GitHub Desktop just created (the one from step 4 above) — so
   `Dockerfile`, `app/`, `docker-compose.yml`, etc. sit directly inside
   `posterbridge/`, replacing the placeholder README if asked.
3. Switch back to **GitHub Desktop**. It will automatically notice all the
   new/changed files listed on the left under "Changes".
4. At the bottom-left, type a commit message, e.g. `Initial PosterBridge
   commit`.
5. Click **Commit to main**.
6. Click **Push origin** at the top (this uploads your commit to GitHub).

### Part 4 — Let GitHub build and publish the Docker image

Pushing to `main` automatically triggers the included GitHub Actions
workflow (`.github/workflows/docker-publish.yml`), which builds the Docker
image and pushes it to GHCR (`ghcr.io`) — no extra setup needed, since it
uses GitHub's own built-in `GITHUB_TOKEN`.

1. On github.com, open your `posterbridge` repository.
2. Click the **Actions** tab. You should see a workflow run in progress
   ("Build and publish to GHCR"). Wait for it to turn green (a few
   minutes).
3. Once it's done, go to your repository's main page → look at the
   right-hand sidebar → **Packages**. Click the `posterbridge` package that
   now appears there.
4. On the package page, click **Package settings** (right sidebar) →
   scroll to **Danger Zone** → **Change visibility** → set it to
   **Public**, and confirm. (First-time-only step: GHCR packages default
   to private even in a public repo.)
5. Note the exact image path shown at the top of that package page — it'll
   be `ghcr.io/YOUR_GITHUB_USERNAME/posterbridge`.

### Part 5 — Deploy on your Docker Linux server

1. On your Linux server, create a folder, e.g.:
   ```bash
   mkdir -p ~/posterbridge && cd ~/posterbridge
   ```
2. Copy `docker-compose.yml` and `.env.example` from the project into this
   folder (`scp`, or just create them with `nano`/your editor of choice —
   copy-paste the contents).
3. Edit `docker-compose.yml`'s `image:` line to match the path from Part 4
   step 5, e.g.:
   ```yaml
   image: ghcr.io/YOUR_GITHUB_USERNAME/posterbridge:latest
   ```
4. Rename `.env.example` to `.env` and fill in your API keys and any
   settings you want to change:
   ```bash
   mv .env.example .env
   nano .env
   ```
5. Start it:
   ```bash
   docker compose up -d
   ```
6. Check it's healthy:
   ```bash
   docker compose logs -f
   curl http://localhost:8000/health
   ```
7. Point AIOMetadata at `http://YOUR_SERVER_IP:8000/...` as shown above.

### Updating later

Whenever you want to change something:

1. Edit files locally, then in GitHub Desktop: **Commit to main** → **Push
   origin**. This re-triggers the GHCR build automatically.
2. Wait for the Actions tab to go green.
3. On your server:
   ```bash
   docker compose pull && docker compose up -d
   ```

## Customising the notable studio/director/cast lists or sash priority

- Sash priority order: set `SASH_PRIORITY` in `.env` (comma-separated slot
  names — see `app/config.py`'s `SASH_PRIORITY` list for every valid name).
- Studios/directors/cast: drop a JSON file at
  `./posterbridge-cache/discovery_overrides.json` on the host (this path is
  already inside the compose volume mount) — see the docstring at the top
  of `app/sash/discovery.py` for the format.

## Known limitations (v1)

- Runs as a single process/worker — the IMDb-dataset refresh coordination
  in `app/cache.py` assumes this; don't set uvicorn `--workers` above 1
  without revisiting that.
- Cult Classic / Based on a True Story / Metacritic Must-See sashes require
  an MDBList API key (free tier works) since they're sourced from MDBList's
  keyword tags — Golden Globe, Emmy, festival, trending, top-rated, and
  release-status sashes don't need one.
- Backdrops and logos never get a sash overlay (only posters do) — this was
  a bug in the first draft, fixed.
