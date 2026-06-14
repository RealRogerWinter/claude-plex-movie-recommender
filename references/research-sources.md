# Research sources — how to cross-check recommendations

The point of the skill is *triangulation*: a title that shows up across an algorithm, an editor's
list, and a fan thread — and fits a real gap in the library — is a far better pick than anything one
source suggests alone. Use `WebSearch` + `WebFetch` (and TMDB for canonical metadata/posters).

## Recommendation engines (the algorithmic spine)
- **TMDB** — `https://www.themoviedb.org/movie/<id>` and `/tv/<id>` have **Recommendations** and
  **Similar** tabs. Also the canonical source for posters: `https://image.tmdb.org/t/p/w500<path>`.
  If a `TMDB_API_KEY` is set, prefer the API (`/movie/{id}/recommendations`, `/search/movie`).
- **TasteDive** (`tastedive.com`) — purpose-built "if you like X you'll like Y" across media. Great
  for cross-domain leaps. API: `https://tastedive.com/api/similar?q=<title>&type=movies`.
- **Trakt** (`trakt.tv/movies/<slug>/related`) — community "related" lists, strong for TV.

## Editorial & list sources (taste & context)
- "If you liked X, watch Y" articles; director/era retrospectives; "best <genre> of the <decade>".
- **Letterboxd** — a film's page + its *Similar Films*; curated lists are excellent for cinephile taste.
- **Metacritic / Rotten Tomatoes** — "More like this" rails and critic context.
- **IMDb** — "More like this" + keywords; useful for connective tissue (shared keywords/people).

## Community signal (the human cross-check)
- **Reddit**: r/MovieSuggestions, r/ifyoulikeblank, r/TrueFilm, r/televisionsuggestions,
  r/ifyoulikeblank — search `site:reddit.com <title> recommendations`. Read the *replies*, not just OPs.
- Forum/blog comment threads, "you might also like" discussions.

## Ratings — a filter, never the target
Pull IMDb (/10), RT (%), Letterboxd (/5), Metacritic for display and sanity-checking. But weight
*fit over score*: a 6.9 cult film aimed straight at the owner's taste beats a 7.8 crowd-pleaser they'd
find generic. Record ratings; let taste rank.

## Availability (optional polish)
- **JustWatch** (`justwatch.com`) — where a title streams/rents, for the "where to watch" line.

## Discipline that keeps quality high
1. **Exclude what's owned.** Always check a candidate against the library (title + year + aliases)
   before proposing it. Re-recommending owned titles is the #1 way to lose trust.
2. **Cross-check ≥2 sources** before trusting a candidate; record each in `sources[]` so claims are traceable.
3. **Tie every pick to the library** with a *specific* relationship (shared director/theme/structure/
   tone/actor) — never "both are sci-fi".
4. **Diversify**: mix safe and adventurous, vary era/country/format. Don't return five sequels of one film.
5. **Be honest about uncertainty** — lower `confidence` rather than inventing a source.
