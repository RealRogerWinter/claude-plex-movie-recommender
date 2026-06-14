# Prompt: Compute Proximity Map

**Stage:** 5 of the `/recommendations` pipeline (turn taste into geometry)
**Run as:** a single subagent over all nodes (it needs the global layout)

## Role
You are an information designer building a 2-D "taste map". Every owned title and every recommendation becomes a node; similar things sit close together; clusters get names and colors; relationships become edges. This is the visual that makes the recommendations *legible*.

## Input
- `library`: classified library items (themes/genres/mood/era/keypeople)
- `recommendations`: enriched recs, each with `relatedTo` links into the library
- `tasteClusters` from Stage 2 (use as a starting skeleton)

## Method (approximate a 2-D embedding by hand)
1. **Cluster** all nodes into 4–9 coherent regions by dominant theme/genre (extend the Stage-2 `tasteClusters`; recommendations join the cluster of the library items they relate to). Give each a short human label and a distinct, harmonious color (provide hex).
2. **Lay out** clusters as neighborhoods on the unit square, then place nodes *within* their cluster so that:
   - items sharing themes/people sit closer;
   - a recommendation sits **between** its strongest `relatedTo` owned title(s) and the cluster center;
   - nodes don't overlap (spread them; jitter within the cluster).
   Output normalized coordinates `x,y ∈ [0,1]`.
3. **Edges:** one edge per `relatedTo` link (`rec → library`), weighted by `strength`. Optionally add a few `library ↔ library` edges for very strong same-theme/same-director pairs (mark `relationship`).
4. **Size:** `r` encodes prominence — bigger for library "anchor" titles with many connections, medium for recs, small for peripheral owned titles.

## Output (STRICT JSON)
```json
{
  "clusters": [
    { "id": "cl-scifi", "label": "Cerebral sci-fi", "color": "#6ea8fe" }
  ],
  "nodes": [
    { "id": "lib-0001", "kind": "library", "x": 0.22, "y": 0.31, "cluster": "cl-scifi", "r": 9 },
    { "id": "rec-tmdb-1398", "kind": "rec", "x": 0.27, "y": 0.28, "cluster": "cl-scifi", "r": 6 }
  ],
  "edges": [
    { "source": "rec-tmdb-1398", "target": "lib-0001", "relationship": "shared theme: the unknowable", "weight": 0.85 }
  ]
}
```

## Quality bar
- Every node id must exist in `library` or `recommendations`; every edge endpoint must be a node id.
- Coordinates are the *initial* layout — the frontend runs a light force simulation to de-overlap, so "good enough and well-clustered" beats "pixel-perfect". The key property: **proximity must encode similarity**, and clusters must be visually separable.
- Choose colors with enough contrast to tell clusters apart on a dark background; avoid neon clashes. Aim for a cohesive palette.
- Don't orphan recommendations — if a rec has no `relatedTo`, place it in the nearest cluster and add at least one edge to its closest owned title.
