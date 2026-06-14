# Prompt: Discovery Cluster (synthesize a new category from genre trends)

**Stage:** alternate to Stage 2/3 — runs when the **discovery** flag is set
**Run as:** a single subagent over the whole (classified) library, before research

## Why this exists
Normal runs recommend *within* the taste regions the library already implies. **Discovery** does the
opposite: it studies the library's **genre + theme distribution** and invents **one entirely new category
cluster** — a throughline the collection is *reaching toward* but doesn't yet have as its own region. It's
how the owner finds a corner of cinema they didn't know they were circling.

## Input
- the classified library (Stage 1 output: per-title primaryGenre/subgenres/themes/mood/era/keypeople)
- optionally the taste profile (Stage 2) for context

## Task
1. **Analyze the genre/theme landscape.** Tally genres, subgenres, themes, eras, and the *combinations*
   that recur (e.g. "sci-fi × grief", "crime × institutions", "docs × wilderness"). Note adjacencies the
   owner over-indexes on and the bridges *between* their clusters.
2. **Synthesize ONE new cluster** that is genuinely novel for this library — not a relabel of an existing
   region. It should sit at an intersection or just beyond the frontier of what they own: a specific,
   nameable category (a movement, a cross-genre mode, a national wave, a formal lineage, a tonal niche)
   that their genre trends predict they'd love. Give it a vivid label, a one-line rationale grounded in the
   tally, a color, and 3–6 **seed titles from THEIR library** that point toward it.
   - **Ground it in 2–3 SPECIFIC owned titles whose pairing is unusual** — name them in the rationale, and
     build the cluster from *their* shared thread. "They own A, B and C, which together imply X" is far
     stronger than "they like drama, so X." The seeds are the proof the cluster is theirs, not a guess.
   - **Resist the prestige default.** A few clusters are seductive on almost any arthouse-leaning shelf —
     "ecological/slow cinema," "elevated horror," "lonely-men neo-noir." They're the path of least
     resistance, so they tend to surface even when the library doesn't truly center them. Reach for them
     ONLY if this specific collection clearly does; otherwise find the synthesis that would *surprise*
     someone reading these exact shelves. A good test: if a totally different library could plausibly yield
     the same cluster, it isn't grounded enough — dig for the one only *this* shelf implies.
3. This cluster becomes the sole focus of the research stage that follows. The **seeds** stay as owned
   anchors (they're where the cluster is rooted, owned or not); the **recommendations** that follow should
   reach for titles they *don't* own — the cluster is a frame for new acquisitions, not a victory lap of the
   genre's canon they already shelve. And each recommended pick must itself clearly *exemplify* the cluster's
   thread, not just sit near it.

## Output (STRICT JSON)
```json
{
  "analysis": "2–4 sentences: the genre/theme trends you found and the gap/intersection they imply.",
  "cluster": {
    "id": "cl-discovery",
    "label": "e.g. Kitchens as Battlefields: Culinary Obsession",
    "color": "#7cc4a3",
    "rationale": "Name the 2–3 owned titles whose unusual pairing implies this, and the genres/themes that combine.",
    "seeds": ["Owned Title A", "Owned Title B", "Owned Title C"],
    "discovery": true
  }
}
```

## Quality bar
- **Novel, not a rename.** If the library already has a "Cerebral Sci-Fi" region, don't return that —
  return something *adjacent and new* (e.g. "Eastern Bloc Sci-Fi Parables"). Defend the novelty in `analysis`.
- Ground it in the ACTUAL tally — name the genre/theme combinations that justify it. No generic "you like
  drama, try more drama."
- Seeds must be titles the owner actually owns (they anchor the new cluster on the map).
- Specific + nameable beats broad. One sharp category the research stage can mine deeply.
