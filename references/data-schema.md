# `data.json` — the single source of truth

Every stage of the pipeline reads or writes pieces of one JSON file. The frontend
(`index.html` + `map.html`) consumes only this file, so if `data.json` is valid the
site renders. Keep this contract stable.

```jsonc
{
  "meta": {
    "generatedAt": "2026-06-14",        // ISO date, stamped by build_site.py
    "libraryTitle": "My Recommendation Atlas",
    "counts": { "library": 731, "recommendations": 42, "clusters": 6 },
    "run": {
      "round": 3,                       // increments every run; recs are tagged with the round that produced them
      "previousRunAt": "2026-05-30",
      "sinceLast": {                    // the diff that powers the feedback loop (from track_state.py)
        "added":   [{ "id": "lib-9001", "title": "Stalker", "year": "1979", "type": "movie", "wasRecommended": true }],
        "removed": [{ "title": "Old Movie", "year": "2009", "type": "movie" }],
        "acquiredFromRecs": ["rec-tmdb-1398"],  // recs the owner actually added since last run = strong positive signal
        "headline": "You added 4 titles since last time — 1 was one of our picks. 6 fresh recommendations this round."
      }
    },
    "runs": [                           // OPTIONAL, derived by build_site.py from the ledger:
      { "round": 1, "label": "Run 1 · May 30", "date": "2026-05-30", "count": 4, "isCurrent": false },
      { "round": 2, "label": "Run 2 · Jun 14", "date": "2026-06-14", "count": 2, "isCurrent": true }
    ]
    // ^ the DISTINCT rec rounds, oldest→newest. date = earliest proposedAt in that round (pinned in
    //   state/runs.json so labels never drift); count = recs from that round; isCurrent === run.round.
    //   Absent on old/sample data → the frontend falls back to round===meta.run.round. Drives the
    //   client-side run filter + the per-card freshness badge; cards expose data-round + data-fresh.
  },

  "clusters": [
    { "id": "cl-scifi", "label": "Cerebral sci-fi", "color": "#6ea8fe" }
  ],

  "library": [
    {
      "id": "lib-7074",                 // stable; derived from Plex ratingKey
      "title": "2001: A Space Odyssey",
      "type": "movie",                  // "movie" | "show"
      "year": "1968",
      "genres": ["Science Fiction"],    // from Plex
      "themes": ["evolution","ai","the-sublime"],   // from Stage 1
      "mood": ["awe","cold"],
      "director": "Stanley Kubrick",
      "poster": "posters/lib-7074.jpg", // RELATIVE path after build_site downloads it
      "cluster": "cl-scifi"
    }
  ],

  "recommendations": [
    {
      "id": "rec-tmdb-1398",            // stable; derived from tmdbId
      "title": "Stalker",
      "type": "movie",
      "year": "1979",
      "overview": "Spoiler-free one or two sentences.",
      "poster": "posters/rec-tmdb-1398.jpg",
      "ratings": { "imdb": "8.1", "rt": "100%", "letterboxd": "4.3", "metacritic": "" },
      "imdbId": "tt0079944",        // optional → direct IMDb link; else the card links to an IMDb search
      "rtUrl": "https://www.rottentomatoes.com/m/stalker",  // optional → direct RT link; else an RT search
      "runtime": "162 min",
      "availability": "Max, Criterion Channel",
      "seerr": { "statusCode": 0, "status": "none", "url": "https://requests.example.org/movie/1398" },
                                        // added by build_site via the Seerr API: real library availability
                                        // (statusCode 5 available / 4 partial / 3 processing / 2 pending / 0 none)
                                        // + a request deep-link (requesting reuses Seerr's own login)
      "kind": "adventurous",            // "safe" | "adventurous"
      "score": 0.91,                    // overall fit 0..1, for sort order
      "cluster": "cl-scifi",
      "round": 3,                       // which run proposed it (recs accumulate; newest round is highlighted)
      "proposedAt": "2026-06-14",
      "status": "active",               // "active" = standing pick | "acquired" = owner added it (shown with a ✓)
      "supersedesSignal": "leaned into 'the-sublime' after you added Annihilation",  // optional: why this round surfaced it
      "sources": [{ "name": "Letterboxd similar", "note": "on Annihilation's page" }],
      "relatedTo": [
        { "libraryId": "lib-7074", "libraryTitle": "2001: A Space Odyssey",
          "relationship": "the-sublime + slow philosophical sci-fi",
          "strength": 0.85,
          "why": "Like *2001*, it treats the unknowable as something to sit with, not solve." }
      ]
    }
  ],

  "map": {
    "nodes": [
      { "id": "lib-7074", "kind": "library", "x": 0.22, "y": 0.31, "cluster": "cl-scifi", "r": 9 },
      { "id": "rec-tmdb-1398", "kind": "rec", "x": 0.27, "y": 0.28, "cluster": "cl-scifi", "r": 6 }
    ],
    "edges": [
      { "source": "rec-tmdb-1398", "target": "lib-7074", "relationship": "the-sublime", "weight": 0.85 }
    ]
  },

  "users": [                            // OPTIONAL — per-user recommendations (Tautulli watch history)
    {
      "id": "u-alice",                   // "u-" + slug (lowercased alphanumeric username)
      "label": "Alice",                  // friendly name when known (library.tautulli.users list), else the slug
      "clusters": [ /* same shape as top-level clusters — this user's taste regions (id/label/color) */ ],
      "recommendations": [ /* rec objects with the SAME schema as data.recommendations above */ ]
    }
  ]
}
```

`users` is added by `build_site.py` only when `personal_recommendations` is true and at least one
per-user ledger exists. The library-wide `recommendations` and the top-level `map` are the **Everyone**
view. The frontend reads `users` and, when present & non-empty, shows a tab bar atop the recommendations
section: **Everyone** (default — `data.recommendations`) plus one tab per user. Switching to a user tab
swaps the cards **and re-renders the constellation to that user's picks** — the map is derived client-side
from each rec's `relatedTo` (nodes = the user's recs + the library titles they anchor to; `user.clusters`
gives the colors/legend, with a client-side fallback for any missing def). The **Everyone** tab restores
the library-wide map. Absent/empty `users` renders exactly as before (no tab bar).

## Invariants the frontend relies on
- Every `map.nodes[].id` must also exist in `library` or `recommendations` (the map looks up
  poster/title/overview by id). Every `map.edges[]` endpoint must be a node id.
- Every `*.cluster` must be a `clusters[].id`. Colors come from `clusters`, so the cards and the
  map agree on color automatically.
- `poster` is either a **relative path** (`posters/<id>.jpg`, preferred — self-contained &
  token-free) or `""` (the UI renders a styled placeholder). Never a `localhost:32400` URL on a
  published site: that LAN URL carries the Plex token and won't load for the public.
- Coordinates are `0..1`; the map normalizes them to the viewport and runs a light force pass to
  de-overlap, so approximate-but-well-clustered positions are fine.
- `users[*].recommendations[]` use the **exact same** rec schema as `recommendations[]`, so the same
  card renderer (and the same Seerr availability/request stamping) applies to every tab. Per-user recs
  do **not** appear in `map.nodes`; the map is library-wide only.
- `meta.runs[*].round` values are exactly the distinct `round` values present across `recommendations[]`
  (every `rec.round` appears in `meta.runs` when `meta.runs` is present). The frontend **never requires**
  `meta.runs` — it derives the run list and freshness from `rec.round` + `rec.proposedAt` when it's absent,
  so old/sample `data.json` (with only `meta.run`) renders identically.

## How the file is assembled
`scan_library.py` writes `library` (sans themes/cluster). Stages 1–7 (driven by the prompts in
`prompts/`) add `themes`/`mood`/`cluster` to library items and produce `recommendations`,
`clusters`, and `map`. `build_site.py` stamps `meta`, downloads every referenced poster into
`site/posters/`, rewrites `poster` fields to relative paths, and copies the templates beside it.

---

## Run state, history & the feedback loop

The skill is **stateful across runs**. State lives in the working dir (default `~/recommendations/state/`,
override with `--workdir`), is managed by `scripts/track_state.py`, and is *not* part of the published
site (except as the small `meta.run.sinceLast` summary).

```
state/
├── library-latest.json        # full snapshot of every movie/show found THIS run (the "list it found")
├── library-latest.txt         # same, human-readable: "Title (Year) [movie]" per line
├── library-previous.json      # the prior snapshot — diffed against latest to find added/removed
├── preferences.json           # evolving taste weights (seeded by Stage 2, nudged each run by the diff)
├── ledger.json                # EVERY recommendation ever made, with round + status (the append-only memory)
├── last-run.json              # { date, round } of the most recent run
├── runs.json                  # append-only { "<round>": {date,label} } — pins each run's representative
│                              #   date+label the FIRST time it's seen so meta.runs is stable across rebuilds
└── runs/<ISO-timestamp>/      # archived library.json + data.json + diff.json for each run
```

### Freshness model (drives the run filter + the per-card badge)

`build_site.py` derives `meta.runs[]` from the ledger; the frontend turns each rec's `round` into a
**freshness tier** (shared by the card badge/line and the run-filter pills):

- **current** — `round === meta.run.round`: the newest run. Card shows the gold **"new this round"**
  badge and a gold **"Latest run · <age>"** line; the filter's **Latest** pill selects these.
- **recent** — the run immediately before the latest: quiet **"Run N"** badge + **"Run N · last week"** line.
- **older** — anything earlier: same quiet treatment, labelled by run + relative age (**"3 weeks ago"**).
- **acquired** — `status === "acquired"`: sits **outside** the ladder, keeps its **✓ in your library** badge.

Each card carries `data-round` and `data-fresh="<tier>"`, so the **run filter** shows/hides cards purely
by toggling the `hidden` attribute (no re-render, no reload) and collapses now-empty cluster carousels.
When `meta.runs` is absent the same tiers are derived from `round` vs `meta.run.round` + `proposedAt`.

### Per-user state (when `personal_recommendations` is on)

Each user the skill recommends for gets an **isolated mini-workdir** under the main one, with the
same `state/` + `work/` layout — so the existing pipeline runs against it unchanged:

```
<workdir>/users/<slug>/        # slug = lowercased alphanumeric username, e.g. "alice"
├── state/
│   ├── library-latest.json    # the user's BASIS — what they've watched (from Tautulli, shaped like
│   │                          #   the library snapshot: {id,title,type,year,genres,director,summary,
│   │                          #   poster,weight}), written by scan_library.py --user NAME
│   ├── library-latest.txt     # human-readable list of that basis
│   ├── ledger.json            # the user's own append-only recommendation memory
│   └── …                      # preferences.json, runs/ — same as the main state/
└── work/                      # per-user diff.json, taste.json, recommendations.json, map.json, …
```

`scan_library.py --user NAME` (source `tautulli-user`) writes the basis; the pipeline then runs with
`workdir = <workdir>/users/<slug>`; `build_site.py` folds each user's active/acquired ledger entries
into `data.users[]` (above). The Tautulli API key is read at runtime and **never** stored or printed.

**The loop, each run:**
1. `scan_library.py` lists everything currently in Plex → `library-latest.json` (+ `.txt`).
2. `track_state.py` diffs latest vs previous → **added** / **removed** titles, and checks the **ledger**:
   any added title that matches a prior recommendation is marked `status:"acquired"` (a strong *yes,
   more like this*); standing picks the owner keeps skipping are nudged down but **kept**.
3. Stage 7 (`prompts/07-evolve-preferences.md`) folds the diff into `preferences.json` — leaning into
   what was added, easing off what was passed over.
4. Stage 3 generates **new** recommendations using the evolved preferences, **excluding** owned titles
   *and* still-active ledger picks, then **appends** them to the ledger with the next `round` number.
5. `build_site.py` assembles `data.json` from the *whole* ledger (active + acquired) + current library,
   so the page shows the accumulated history: newest round flagged "New", acquired picks flagged ✓.

The matching key for diffs and "already recommended/owned" checks is the **normalized
`(title, year, type)`** tuple (lowercased, articles/punctuation stripped), not the Plex `ratingKey`
(which changes when media is re-added across tiers).
