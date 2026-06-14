# Prompt: Enrich Recommendation

**Stage:** 4 of the `/recommendations` pipeline (make each pick presentable)
**Run as:** batched subagents (e.g. 10 candidates each) after dedup

## Role
You fetch the canonical metadata, artwork, and ratings for each accepted candidate so the HTML page looks like a real catalog, not a list of titles.

## Input
A candidate from Stage 3 (`title`, `type`, `year`, plus its `relatedTo`/`sources`/`whyOverall`).

## Method
- Resolve the title on **TMDB** (the canonical source for posters + overview). Capture the TMDB id and build an absolute poster URL: `https://image.tmdb.org/t/p/w500<poster_path>`. Confirm year/type to avoid same-name collisions.
- Write a complete, spoiler-free `overview` of **2–4 sentences** (rewrite TMDB's if clunky) — the card shows it in **full, untruncated**, so make it a real description, not a teaser.
- Gather ratings where readily available: IMDb (xx/10), Rotten Tomatoes (xx%), Letterboxd (x.x/5), Metacritic. Leave blank rather than guess.
- Capture `imdbId` (from TMDB external_ids → `imdb_id`, e.g. `tt0079944`) and the Rotten Tomatoes page `rtUrl` so every card deep-links to IMDb + RT. If you can't find one, omit it — the card falls back to a precise search link.
- Note `availability` if discoverable (streaming/where to watch) via JustWatch — optional.

## Output (STRICT JSON)
```json
{
  "id": "rec-0007",
  "title": "Stalker",
  "type": "movie",
  "year": "1979",
  "tmdbId": 1398,
  "overview": "Spoiler-free, 2–4 complete sentences (shown in full on the card).",
  "poster": "https://image.tmdb.org/t/p/w500/xxxxxxxx.jpg",
  "runtime": "162 min",
  "ratings": { "imdb": "8.1", "rt": "100%", "letterboxd": "4.3", "metacritic": "" },
  "imdbId": "tt0079944",
  "rtUrl": "https://www.rottentomatoes.com/m/stalker",
  "availability": "Max, Criterion Channel"
}
```

## Quality bar
- **`poster` must be a working absolute URL.** If TMDB has no poster, try Wikipedia/Wikidata; if still none, set `"poster": ""` (the template renders a styled placeholder) — never link a broken image.
- Keep the `id` stable across runs when possible (derive from tmdbId, e.g. `rec-tmdb-1398`) so the map stays consistent run-to-run.
- Don't fabricate ratings or runtimes. Empty string is honest; a made-up number poisons trust.
- Preserve the incoming `relatedTo`, `sources`, `whyOverall`, `kind` fields — Stage 8 merges them with this metadata.
