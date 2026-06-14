# Configuration reference

Everything installation-specific lives in **one JSON config file**, so the skill source stays generic and
shareable. Copy [`config.example.json`](../config.example.json) to a config path and edit it; nothing in it
is secret (tokens/keys are read at runtime — see [Secrets](#how-secrets-are-read-at-runtime)).

```bash
mkdir -p ~/.config/recommendations
cp config.example.json ~/.config/recommendations/config.json
python3 scripts/config.py show     # print the merged, effective config
python3 scripts/config.py path     # print which config file is in effect
python3 scripts/config.py get services.seerr.enabled   # read one value
```

## Resolution order
The first source that exists wins for the file; then env vars override individual values; then built-in
defaults fill the gaps:

1. `--config <path>` flag, or the `REC_CONFIG` environment variable
2. `~/.config/recommendations/config.json`
3. `<skill>/config.json` (a config placed next to the skill)
4. built-in defaults (`scripts/config.py` `DEFAULTS`)

## Environment overrides
Handy for CI or one-off runs without editing the file:

| Variable | Overrides |
|---|---|
| `REC_CONFIG` | path to the config file |
| `REC_WORKDIR` | `workdir` |
| `PLEX_BASE_URL` / `PLEX_PREFS` / `PLEX_CONTAINER` | `library.plex.*` |
| `PLEX_TOKEN` | the Plex token (skips the file/docker lookup) |
| `TMDB_API_KEY` | `research.tmdb_api_key` |
| `TAUTULLI_API_KEY` / `TAUTULLI_CONFIG` | Tautulli key / its config path |
| `SEERR_API_KEY` / `SEERR_SETTINGS` / `SEERR_BASE` | Seerr key / settings path / base URL |

## Fields

### `library`
- **`source`** — library backend. `plex` is implemented today; the field exists so other backends can plug
  in without touching the rest of the skill.
- **`plex`**
  - `base_url` — Plex API root (default `http://localhost:32400`).
  - `prefs_path` — path to `Preferences.xml` (where the token lives). Only needed if the file is readable;
    otherwise the token is fetched via the container (see Secrets).
  - `container` — Plex Docker container name, used for the `docker exec` token fallback.
- **`tautulli`** — only used when `personal_recommendations` is on. See [integrations.md](integrations.md#tautulli--per-user-tabs).
  - `base_url`, `container`, `config_path` (the in-container `config.ini` holding the API key),
  - `users` — `"all"`, or an explicit list of Plex usernames, e.g. `["Alice","Bob"]`. An explicit list also
    gives each tab a friendly label.

### `personal_recommendations`
`true` adds a personalized **tab per Plex user**, driven by each person's *watch history* (via Tautulli)
rather than the whole library. Default `false`.

### `workdir`
Where run state lives: `state/` (snapshots, ledger, preferences), `work/` (per-stage JSON), and the built
`site/`. Default `~/recommendations`. **This is your personal data — keep it out of the shareable repo.**

### `site`
- `title`, `tagline` — the page hero text.

### `deploy`
Read by `scripts/deploy.sh`. See [deploy.md](deploy.md).
- `provider` (`github-pages`), `repo` (`OWNER/REPO`), `domain` (optional custom domain), `branch`,
  `visibility` (`private` | `public` — default private), `git_name`, `git_email`.

### `services.seerr`
Overseerr / Jellyseerr integration. See [integrations.md](integrations.md#seerr--availability--one-click-requests).
- `enabled` — master switch (default `false`).
- `base_url` — Seerr API root (server-side, e.g. `http://localhost:5055`).
- `public_url` — the **public** Seerr URL used for "Request" links on the page.
- `container`, `settings_path` — where the API key is read from (the in-container `settings.json`).

### `research.tmdb_api_key`
Optional. Speeds up and improves poster/metadata enrichment. Without it the skill still resolves posters via
public TMDB image paths where possible. See [integrations.md](integrations.md#tmdb--richer-postersmetadata).

### `bounds`
Tuning knobs passed to the generation engine:
- `sampleForTaste` — how many titles to classify when profiling taste (bigger = richer profile, slower).
- `classifyBatch` — classification batch size.
- `maxClusters` — max taste regions per run.
- `perCluster` — target candidates researched per region.

Raise them for a deep pass, lower them for a quick refresh.

### `modes`
- `daring` — bolder, deeper-cut picks (festival/international/older). Default `false`.
- `discovery` — synthesize ONE brand-new cluster from the library's genre trends, then research it. Default `false`.

Both can also be enabled per-run via the pipeline `args` (`daring: true` / `discovery: true`). See the
"Daring & Discovery modes" section of [`SKILL.md`](../SKILL.md).

## How secrets are read at runtime
No token or API key is ever stored in the config or written into the published site. Each is resolved lazily,
trying the cheapest source first:

- **Plex token** — `PLEX_TOKEN` env → `Preferences.xml` (`prefs_path`) → `docker exec <container> cat …` →
  `sudo` read. Whatever succeeds first is used in memory only.
- **Tautulli API key** — `TAUTULLI_API_KEY` env → the container's `config.ini` (`docker exec`).
- **Seerr API key** — `SEERR_API_KEY` env → the container's `settings.json` (`docker exec`).

If none of a service's sources resolve, that integration simply degrades (e.g. no availability badges) rather
than failing the run.
