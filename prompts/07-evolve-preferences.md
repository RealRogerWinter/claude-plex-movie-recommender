# Prompt: Evolve Preferences (the feedback loop)

**Stage:** 7 of the `/recommendations` pipeline — runs only on the 2nd+ run, before Stage 3
**Run as:** a single subagent

## Why this stage exists
The library is a living thing. Between runs the owner adds titles (sometimes *our* picks, sometimes
their own finds) and occasionally removes some. That delta is the highest-signal taste data we ever
get — far better than guessing from a static snapshot. This stage converts the delta into an updated
preference vector so each round gets sharper instead of repeating itself.

## Input
- `previousPreferences`: `preferences.json` from last run (or the Stage-2 taste profile on run 2).
- `diff`: from `track_state.py` —
  - `added`: titles new since last run, each flagged `wasRecommended: true|false`, **already classified**
    (themes/genres/mood via Stage 1 so you can see the pattern).
  - `removed`: titles gone since last run.
- `ledgerFeedback`: prior recommendations with outcome —
  - `acquired`: picks the owner actually added (**strong positive**).
  - `passed`: picks shown for ≥1 round and still not added (**mild negative** — they saw it, skipped it).

## How to read the signals
- **Acquired our pick** → the themes/people/cluster of that pick are *confirmed*. Up-weight them
  noticeably. This is the loop working; lean in.
- **Added something we didn't suggest** → a taste we under-served. Up-weight its pattern and treat its
  cluster as a growth area (great source of next-round picks).
- **Passed on a pick repeatedly** → down-weight that specific angle *gently*. Don't nuke a whole genre
  over one miss; maybe the pick was wrong, not the taste. Note it so Stage 3 pivots the *approach*.
- **Removed a title** → weak negative (could just be storage cleanup on a tiered server). Small nudge only.

## Output (STRICT JSON) — write this as the new `preferences.json`
```json
{
  "round": 3,
  "tasteSummary": "updated 2–4 sentence prose, noting how taste has shifted",
  "weights": {
    "themes":  [{ "tag": "the-sublime", "weight": 0.0, "delta": "+0.15 (added Stalker, Annihilation)" }],
    "genres":  [{ "tag": "science-fiction", "weight": 0.0, "delta": "+0.05" }],
    "people":  [{ "tag": "andrei-tarkovsky", "weight": 0.0, "delta": "new" }],
    "moods":   [{ "tag": "contemplative", "weight": 0.0, "delta": "0" }]
  },
  "adventurousness": 0.0,
  "leanInto":   ["slow cosmic sci-fi", "Eastern European auteurs"],
  "easeOffOf":  ["mainstream creature-features (passed on 2 picks)"],
  "growthAreas":["international cinema still thin despite interest"],
  "nextRoundGuidance": "2–3 sentences telling Stage 3 exactly where to push this round."
}
```

## Quality bar
- Make the `delta` notes concrete and traceable to specific added/passed titles — this is what makes the
  evolution legible (and shows up in the site's "Since last time" panel).
- Preferences should *move*, not lurch. Weights are smoothed: blend ~70% previous, ~30% new signal,
  unless an acquired-pick gives a clear confirmation worth more.
- `nextRoundGuidance` is the handoff to Stage 3 — be specific about what NEW territory to explore so we
  don't re-propose the same vibe.
