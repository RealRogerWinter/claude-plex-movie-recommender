---
name: recommendations
description: >-
  Use when the user wants movie or TV recommendations, asks "what should I watch",
  wants to know what to add to their Plex / media library / collection, or wants to
  build, refresh, update, or publish their recommendations page.
  Also use for any request to scan the media library and suggest new films or shows
  based on what they already own, build a "because you own X" list, generate the
  recommendation atlas/map, or re-run recommendations to pick up newly added titles.
  Triggers on "recommend", "suggestions", "what to watch", "films/shows like the ones
  I have", "update my recommendations" — even if Plex or the library isn't named explicitly.
license: MIT
---

# /recommendations — a self-tuning recommendation atlas for your Plex library

**This skill is for Plex servers.** It reads your Plex library over the Plex HTTP API (Tautulli and
Overseerr/Jellyseerr add optional per-user and request features — all Plex-ecosystem). The library backend
is pluggable (`library.source`), but Plex is the implemented and supported one.

Scan the Plex library on this server, research the web to find titles the owner does **not**
own but will love, tie each pick to something they already have (and explain *why*), and publish
a rich HTML page + an interactive proximity **map** to a site you configure in `config.json`.
It is **stateful**: every run
diffs the library against the last, learns from what got added, and **appends** a new round of
picks rather than replacing the old ones.

## What it produces
- `index.html` — a "Midnight Cinema Atlas": hero + stats, a **since-last-time** feedback panel, the
  interactive constellation, and recommendation cards grouped by taste region. Each taste region is a
  **horizontal, swipeable carousel** (paginated arrows on desktop, native swipe on touch — no reload).
  Each card: poster, title/year, a **freshness badge + line** (which run produced it + how long ago),
  IMDb + Rotten Tomatoes links, the full overview, *because you have …* links with a one-line why, and
  (when Seerr is configured) a live availability badge + "Request on Seerr" deep-link. A **run filter**
  (pill row under the heading) narrows the visible picks to a given round client-side; it composes with
  the per-user tabs.
- `map.html` — the full-screen constellation: every pick and its library anchors as nodes,
  proximity = similarity, edges = the "because you have X" links.
- `data.json` — the single data file both pages read (schema: `references/data-schema.md`).

## Configuration (what keeps the skill generic + portable)
Everything installation-specific lives in **one config file**, so the skill itself is generic and can be
open-sourced as-is. Resolution order: `--config` / `$REC_CONFIG` → `~/.config/recommendations/config.json`
→ `<skill>/config.json` → built-in defaults. Copy `config.example.json` to one of those paths and edit;
inspect the merged result with `python3 scripts/config.py show`. **Full field-by-field reference (+ env
overrides + how secrets are read):** `references/configuration.md`. **Optional integrations (Plex, Tautulli,
Seerr, TMDB, deploy) and how each degrades:** `references/integrations.md`.

- **library.plex** — `base_url` (default `http://localhost:32400`), `prefs_path`, `container`. The Plex
  token is read at runtime from `Preferences.xml`, falling back to `docker exec <container>` / `sudo` when
  the file is mode-600 unreadable. The token is **never stored or printed**.
- **workdir** — where `state/`, `work/`, `site/` live (default `~/recommendations`).
- **site.title / site.tagline** — the page hero text.
- **deploy** — `provider` (github-pages), `repo`, `domain`, `branch`, `visibility`, `git_name`,
  `git_email`. `deploy.sh` reads these, so a configured publish is just `scripts/deploy.sh`.
- **services.seerr** — point at your Overseerr/Jellyseerr (`base_url`, `public_url`, `container`). When
  `enabled`, `build_site` calls the Seerr API to stamp each card with **real library availability** and a
  **"Request on Seerr"** deep-link — requesting reuses Seerr's own login, so no write key or proxy is needed.
- **research.tmdb_api_key** — optional; speeds up poster/metadata enrichment when set.
- **bounds** — `sampleForTaste`, `classifyBatch`, `maxClusters`, `perCluster` (passed to the engine).

> Assumes **no Node** on the target host — the site is pure static HTML/CSS/vanilla JS + D3 from CDN.
> Don't add a build step. Library source is pluggable via `library.source` (currently `plex`).

## Run it

Prefer the orchestrated path (parallel web research is the slow part). Each run:

```bash
cd ~/.claude/skills/recommendations
WD=~/recommendations
python3 scripts/scan_library.py  --workdir $WD     # Stage 0  → state/library-latest.json (+ .txt list)
python3 scripts/track_state.py   --workdir $WD     # Stage 0.5 → diff vs last run, mark acquired picks
```

Then run the **engine** (`scripts/pipeline.workflow.js`) with the Workflow tool — it fans out the
classify / taste / research / enrich / map stages:

```js
Workflow({ scriptPath: "~/.claude/skills/recommendations/scripts/pipeline.workflow.js",
           args: { skillDir: "$HOME/.claude/skills/recommendations",   // use absolute paths
                   workdir: "$HOME/recommendations",
                   sampleForTaste: 80, maxClusters: 6, perCluster: 8 } })
```

For a deeper pass: raise `sampleForTaste`, `maxClusters`, `perCluster`. For a quick refresh: lower them.
No Workflow tool available? Drive the same stages by hand using the prompts in `prompts/` (see below),
writing each stage's JSON into `$WD/work/`.

Finally assemble, preview, and (when the user confirms) publish:

```bash
python3 scripts/build_site.py --workdir $WD --append $WD/work/recommendations.json
python3 scripts/serve.py      --dir $WD/site            # preview at http://localhost:8000
scripts/deploy.sh                                       # PUBLISH — reads deploy.* from config; gated (see below)
```

## The pipeline (each stage has a reusable prompt in `prompts/`)
| # | Stage | Prompt | Output |
|---|-------|--------|--------|
| 0 | Scan Plex → snapshot | — (`scan_library.py`) | `state/library-latest.json` + `.txt` |
| 0.5 | Diff vs last run, reconcile ledger | — (`track_state.py`) | `work/diff.json`, `work/exclusions.json` |
| 1 | Classify what we own | `01-classify-library.md` | themes/mood/era per title |
| 2 | Build taste profile | `02-taste-profile.md` | `work/taste.json`, `state/preferences.json` |
| 7 | Evolve preferences from the diff *(run 2+)* | `07-evolve-preferences.md` | updated `state/preferences.json` |
| 3 | Research recommendations (web) | `03-generate-recommendations.md` | `work/cand-*.json` |
| 4 | Enrich (posters, ratings, overview) | `04-enrich-recommendation.md` | `work/enriched-*.json` |
| 6 | Explain each link, vividly | `06-relationship-explainer.md` | `relatedTo[].why` |
| 5 | Lay out the proximity map | `05-compute-proximity.md` | `work/map.json`, `work/clusters.json` |
| — | Assemble + render + posters | — (`build_site.py`) | `site/` |

The prompts are the heart of the skill — they carry the quality bar (specific theme tags, "tie every pick
to the library", triangulate ≥2 sources, never re-recommend owned titles). Read them before driving a stage.

## The feedback loop (what makes re-runs get smarter)
State persists in `~/recommendations/state/` (details: `references/data-schema.md`).
- `scan_library.py` writes the full **list of everything found** this run.
- `track_state.py` diffs it against the previous run. Titles the owner **added** are taste signal; any that
  match a prior recommendation are marked **acquired** (a strong *yes, more of this*) and shown with a ✓.
  Standing picks they keep skipping are **kept but down-weighted** — recommendations accumulate, never reset.
- `07-evolve-preferences.md` folds the diff into `preferences.json`; Stage 3 leans into what was added and
  excludes both owned titles and still-active prior picks, so each round explores **new** ground.
- The site's "Since last time" panel surfaces this so the owner can see the system learning.

## Daring & Discovery modes
Two optional flags reshape a run — set `modes.daring` / `modes.discovery` in config, or pass `daring: true`
/ `discovery: true` in the pipeline `args`:
- **daring** — pushes the research stage hard past the safe zone (deep cuts, festival/international,
  formally bold/polarizing picks). Recs are tagged `mode: "daring"`; the run is labelled "Run N · Daring".
- **discovery** — *before* researching, synthesizes ONE brand-new category cluster from the library's
  **genre/theme trends** (a novel intersection it doesn't already have — see `prompts/08-discovery-cluster.md`)
  and researches that. Recs are tagged `mode: "discovery"`; the synthesized cluster shows up on the map and
  as its own carousel.

Tag the build so the run is labelled + cards badged by mode:
```bash
# after running pipeline.workflow.js with args { ..., daring: true }  (or discovery: true)
python3 scripts/build_site.py --workdir $WD --append $WD/work/recommendations.json --mode daring
```
The run filter + freshness badges surface which run/mode each pick came from.

> **Both modes need a basis with breadth to shine.** On a large, diverse library they produce their best
> work (a tightly-themed novel cluster, genuine older/festival deep cuts). On a **thin basis (≲ 20 distinct
> titles)** — common for a per-user tab driven by a short watch history — daring tends to drift *newer*
> instead of deeper and reuses the same few anchors, and discovery leans on generic prestige priors
> ("eco/slow cinema," "elevated horror") rather than that person's actual taste. For small per-user bases,
> prefer standard mode, or widen the basis first (more watch history, or blend in the library taste).

**Measure a pass.** After folding a daring/discovery round, run `python3 scripts/analyze_runs.py` (reads the
built `site/data.json`). It tables every target × mode — Seerr availability, era profile, *anchor novelty*
(how much a bold run reused the standard run's library anchors vs. explored new ones), and flags thin picks.
It's how you tell whether a daring/discovery run actually broke new ground, and which prompt to tune when it didn't.

## Per-user recommendations (Tautulli)
Set `personal_recommendations: true` and `library.tautulli.users` (a list of names, or `"all"`) to add a
personalized **tab per Plex user**, driven by their **watch history** (via Tautulli) rather than the whole
library. The Tautulli API key is read at runtime like the Plex token (env → `docker exec` → `sudo`).

Per user (slug = lowercased-alnum username) into an isolated `~/recommendations/users/<slug>/` workdir:
```bash
WD=~/recommendations; U=alice; SLUG=alice   # U = the exact Plex username; SLUG = its lowercased-alnum form
python3 scripts/scan_library.py --user "$U" --workdir $WD          # their watched basis (Tautulli) → users/<slug>/state
python3 scripts/track_state.py  --workdir $WD/users/$SLUG          # per-user diff + ledger
# run scripts/pipeline.workflow.js with args.workdir = $WD/users/$SLUG  (their taste → their picks)
python3 scripts/build_site.py   --workdir $WD/users/$SLUG --append $WD/users/$SLUG/work/recommendations.json --out /tmp/null-$SLUG  # just to fold the round into their ledger
```
Then a normal `python3 scripts/build_site.py --workdir $WD` folds every `users/<slug>/` ledger into
`data.users[]` (each with its own `clusters`), which the page surfaces as extra tabs alongside the
"Everyone" tab. **Selecting a user re-renders the constellation to *their* picks** — only that person's
recommendations and the library titles they anchor to — and the "Everyone" tab restores the library-wide
atlas. (The per-user map is derived client-side from each rec's `relatedTo` links, so it always matches the
ledger; no extra layout pass is needed.) Per-user recs get the same Seerr availability + request treatment;
everything is served behind the same gate. See `references/data-schema.md` for the shape.

## Make it beautiful
The bundled templates already commit to a distinctive aesthetic. To tailor the look to the specific
library's mood (e.g. a noir-heavy shelf vs. a sci-fi one), refine `assets/templates/` before building.

**REQUIRED SUB-SKILL:** Use frontend-design when restyling the page — keep the data-binding hooks
(`render.js` ids/classes, `data.json` schema, `RecMap.init`) intact; change only the look. Honor its
principles: bold direction, characterful type, cohesive palette via CSS vars, motion with restraint,
no generic AI-slop layouts.

## Publishing is gated
Deploying makes the library + picks **world-readable and indexable**. Treat the first publish, making the
repo public, and any DNS change as confirm-first actions — surface them to the user and wait. `deploy.sh`
defaults the repo to **private**; `--public` is opt-in. One-time Pages + Cloudflare DNS steps: `references/deploy.md`.

## Files
```
recommendations/
├── SKILL.md
├── config.example.json   copy → ~/.config/recommendations/config.json and edit (all the install specifics)
├── LICENSE               MIT — ready to open-source
├── prompts/        01-07 — the reusable classify/taste/research/enrich/explain/map/evolve prompts
├── references/     configuration.md · integrations.md · deploy.md · data-schema.md · research-sources.md
├── assets/templates/  index.html · map.html · app.css · render.js · map.js · data.sample.json
└── scripts/        config.py · plexlib.py · scan_library.py · track_state.py · build_site.py
                    seerr.py · tautulli.py · request_proxy.py · analyze_runs.py
                    serve.py · deploy.sh · pipeline.workflow.js
```

## Guardrails
- **Never re-recommend an owned or already-listed title** — the prompts enforce it and `build_site.py`
  dedupes again as a safety net (normalized `title+year+type`).
- **Never leak the Plex token or LAN URLs** into the published site — `build_site.py` downloads posters
  locally and blanks anything it can't.
- **Don't touch the `ultimate-plex-stack`.** This skill only *reads* Plex; the server-side deploy option
  is a *separate* compose project.
- **Tie every recommendation to the library with a specific reason.** A pick with no honest "because you
  have X" doesn't ship.
