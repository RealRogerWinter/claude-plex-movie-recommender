# Integrations

The skill needs exactly **one** thing — a library to read (Plex). Everything else is optional and
**degrades gracefully**: leave it off and the corresponding feature simply doesn't appear; turn it on and the
page gets richer. All wiring lives in [`config.json`](configuration.md); secrets are read at runtime and never
stored.

| Integration | Required? | What it adds | Turn on with | If absent |
|---|---|---|---|---|
| **Plex** | ✅ yes | The library to scan + posters | `library.plex.*` | nothing runs |
| **Tautulli** | optional | A personalized **tab per user** from watch history | `personal_recommendations: true` + `library.tautulli.*` | library-wide recs only |
| **Seerr** | optional | Live **availability badges** + one-click **request & auto-approve** | `services.seerr.enabled: true` | cards show no availability/request |
| **TMDB key** | optional | Faster, higher-quality posters & metadata | `research.tmdb_api_key` | best-effort public poster paths |
| **Deploy** | optional | Publish the static site | `deploy.*` → `scripts/deploy.sh` | preview locally only |

---

## Plex — the library (required)
The only hard dependency. The skill reads your sections over the Plex HTTP API and snapshots every movie/show.

- Config: `library.plex.base_url`, `prefs_path`, `container`.
- **Token** is resolved at runtime (`PLEX_TOKEN` env → `Preferences.xml` → `docker exec <container>` → `sudo`)
  and used only in memory — see [configuration.md](configuration.md#how-secrets-are-read-at-runtime).
- The skill only ever **reads** Plex. It never writes to your server or your media-stack compose.

## Tautulli — per-user tabs
Tautulli exposes each Plex user's **watch history**, which the skill turns into a per-person taste profile and
a dedicated tab. Selecting that tab also **re-renders the constellation to just that user's picks**; the
"Everyone" tab restores the library-wide atlas.

- Enable: set `personal_recommendations: true` and list users in `library.tautulli.users` (`"all"` or
  `["Alice","Bob"]` — an explicit list also sets the friendly tab labels).
- The API key is read at runtime from the container's `config.ini` (or `TAUTULLI_API_KEY`).
- Each user runs in an isolated `<workdir>/users/<slug>/` workdir; a final library build folds every user
  ledger into `data.users[]`, which the page renders as tabs.
- **Caveat:** the modes (daring/discovery) need breadth to shine — a thin watch history (≲ 20 distinct
  titles) produces weaker bold/novel picks. Prefer standard mode for light profiles. (See SKILL.md.)

## Seerr — availability + one-click requests
Point at your **Overseerr / Jellyseerr** to make the page actionable: every card gets a live availability
badge, and titles you don't have get a **Request** button that creates the request **and auto-approves it**.

- Enable: `services.seerr.enabled: true`, set `base_url` (server-side API) and `public_url` (the public URL
  used in links). The API key is read at runtime from the container's `settings.json` (or `SEERR_API_KEY`).
- **Availability** is stamped at build time *and* refreshed live in the browser on every load, so a card
  flips from "Request" to "Available" as soon as the item lands — no rebuild needed.
- **Requesting** needs a tiny write path because the browser can't hold the Seerr key. Two options:
  - *Self-host:* run the bundled `scripts/request_proxy.py` behind your reverse proxy (it exposes
    `POST /request` → create+approve and `POST /status` → batch availability, holding the key server-side).
    See the nginx snippet in [deploy.md](deploy.md).
  - *Static host:* omit the proxy — cards still show availability (baked at build) and link out to Seerr's own
    UI to request, reusing Seerr's login.
- Status codes used: `5` available · `4` partially available · `3` processing · `2` pending · else not requested.

## TMDB — richer posters/metadata
A free [TMDB](https://www.themoviedb.org/settings/api) key (`research.tmdb_api_key` or `TMDB_API_KEY`) speeds
up enrichment and improves poster/overview/year quality. Without it, the skill still resolves posters via
public TMDB image paths and Plex thumbnails where it can.

## Deploy — publishing
The build is a self-contained static site (`<workdir>/site/`). `scripts/deploy.sh` reads `deploy.*` and
publishes to GitHub Pages; a Cloudflare Tunnel self-host (with Basic Auth) is also documented. **Publishing is
public and outward-facing — treat the first publish and any DNS change as confirm-first.** Full instructions,
including the auth gate and the Seerr request-proxy wiring, are in [deploy.md](deploy.md).
