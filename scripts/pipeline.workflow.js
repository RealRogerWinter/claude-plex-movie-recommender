/* ============================================================================
   /recommendations — the generation engine (Workflow script).

   Assumes scan_library.py + track_state.py have already run (so state/ and
   work/diff.json + work/exclusions.json exist). Drives the LLM stages, each an
   agent that reads/writes JSON in <workdir>/work guided by a bundled prompt:

     Prep+Classify -> Taste(+Evolve) -> Research -> Enrich -> Map

   Then the caller runs build_site.py to assemble + render. Bounded by args so a
   quick pass and a deep pass use the same engine.

   args = { skillDir, workdir, title?, sampleForTaste?, classifyBatch?,
            maxClusters?, perCluster?, round? }
   ========================================================================== */
export const meta = {
  name: 'recommendations-pipeline',
  description: 'Generate bespoke film/TV recommendations from a scanned Plex library: classify, profile taste, research the web, enrich, and lay out a proximity map.',
  phases: [
    { title: 'Prep & classify' }, { title: 'Taste' }, { title: 'Research' },
    { title: 'Enrich' }, { title: 'Map' },
  ],
}

const A = args || {}
const SKILL = A.skillDir || '~/.claude/skills/recommendations'   // the caller (SKILL.md) always passes
const WD = A.workdir || '~/recommendations'                      // absolute skillDir/workdir; these are fallbacks
const SAMPLE = A.sampleForTaste ?? 80
const BATCH = A.classifyBatch ?? 20
const MAXCL = A.maxClusters ?? 6
const PER = A.perCluster ?? 8
const DARING = !!A.daring          // bolder, deeper-cut picks
const DISCOVERY = !!A.discovery    // synthesize one brand-new cluster from genre trends
const P = n => `${SKILL}/prompts/${n}`
const W = f => `${WD}/work/${f}`
const S = f => `${WD}/state/${f}`

// ---- Prep & classify -------------------------------------------------------
phase('Prep & classify')
const prep = await agent(
  `Prepare the library for taste analysis.
Read ${S('library-latest.json')} (an array of {id,title,type,year,genres,director,summary}).
Pick a representative sample of up to ${SAMPLE} titles that spans the collection's genres, eras and
both movies and shows (favor distinctive/auteur titles over duplicates of a franchise). Split the
sample into batches of ${BATCH} and write each batch as ${W('classify-in-<i>.json')} (i = 0,1,2,...).
Return the number of batches written and the sample size.`,
  { label: 'prep:sample', phase: 'Prep & classify',
    schema: { type: 'object', properties: { batches: { type: 'integer' }, sampleSize: { type: 'integer' } }, required: ['batches'] } })

const K = Math.max(0, (prep && prep.batches) || 0)
log(`Classifying ${prep ? prep.sampleSize : 0} titles in ${K} batches`)

await parallel(Array.from({ length: K }, (_, i) => () => agent(
  `Classify a batch of library titles. Read the instructions in ${P('01-classify-library.md')} and follow
its output contract EXACTLY. Input: ${W(`classify-in-${i}.json`)}. Write the resulting JSON array to
${W(`classify-out-${i}.json`)}. Return {"count": N}.`,
  { label: `classify:${i}`, phase: 'Prep & classify',
    schema: { type: 'object', properties: { count: { type: 'integer' } }, required: ['count'] } })))

// ---- Taste profile (+ evolve from the diff on later runs) -------------------
phase('Taste')
const taste = await agent(
  `Build the owner's taste profile. Read every ${W('classify-out-*.json')} (the classified sample) and
follow ${P('02-taste-profile.md')} to produce the profile. ALSO read ${W('diff.json')}: if it exists and
isFirstRun is false, additionally follow ${P('07-evolve-preferences.md')} using the diff (added/removed/
acquired) and the previous ${S('preferences.json')}, and write the evolved result to ${S('preferences.json')}.
On the first run, write the Stage-2 profile to ${S('preferences.json')} as the baseline.
Write the full taste profile to ${W('taste.json')}, and include in it a "clusterPlan": an array of at most
${MAXCL} taste regions, each {id (kebab, e.g. cl-scifi), label, color (hex, cohesive on a dark bg),
seeds:[3-5 owned titles that anchor it]}. Return the clusterPlan.`,
  { label: 'taste:profile', phase: 'Taste',
    schema: { type: 'object', properties: { clusterPlan: { type: 'array', items: {
      type: 'object', properties: { id: { type: 'string' }, label: { type: 'string' }, color: { type: 'string' },
        seeds: { type: 'array', items: { type: 'string' } } }, required: ['id', 'label', 'color'] } } }, required: ['clusterPlan'] } })

let plan = ((taste && taste.clusterPlan) || []).slice(0, MAXCL)

// Discovery mode: synthesize ONE brand-new cluster from the library's genre trends and focus on it.
if (DISCOVERY) {
  phase('Discovery')
  const disc = await agent(
    `DISCOVERY MODE. Read every ${W('classify-out-*.json')} (the classified library sample) and ${W('taste.json')},
then follow ${P('08-discovery-cluster.md')} to SYNTHESIZE ONE brand-new category cluster from the library's
genre/theme trends (a novel intersection it does NOT already have). Write {analysis, cluster} to
${W('discovery.json')} and return the cluster object {id,label,color,seeds}.`,
    { label: 'discovery:synthesize', phase: 'Discovery',
      schema: { type: 'object', properties: { id: { type: 'string' }, label: { type: 'string' }, color: { type: 'string' },
        seeds: { type: 'array', items: { type: 'string' } } }, required: ['id', 'label'] } })
  if (disc && disc.id) plan = [disc]
}
log(`Researching ${plan.length} ${DISCOVERY ? 'discovery' : 'taste'} region(s)${DARING ? ' [DARING]' : ''}: ${plan.map(c => c.label).join(', ')}`)

// ---- Research -> Enrich (pipelined per cluster) ----------------------------
const results = await pipeline(
  plan,
  // Stage 3: web research for this region
  (c) => agent(
    `Recommend titles for the taste region "${c.label}" (id ${c.id}, anchored by: ${(c.seeds || []).join(', ')}).
Follow ${P('03-generate-recommendations.md')} and ${SKILL}/references/research-sources.md. Use real web
research (WebSearch/WebFetch — load them via ToolSearch if needed). Read ${W('taste.json')} for preferences
and ${W('exclusions.json')} for titles to EXCLUDE (owned + already-recommended). Target ~${PER} candidates.${DARING ? ' DARING MODE: ON — follow the prompt Daring-mode guidance: bold deep cuts, festival/international/independent, skip the obvious mainstream pick.' : ''}
Write the JSON array to ${W(`cand-${c.id}.json`)} and return {"cluster":"${c.id}","count":N}.`,
    { label: `research:${c.id}`, phase: 'Research',
      schema: { type: 'object', properties: { cluster: { type: 'string' }, count: { type: 'integer' } }, required: ['count'] } }),
  // Stage 4 (+6): enrich with posters/metadata and polish the "why"
  (_r, c) => agent(
    `Enrich the candidates in ${W(`cand-${c.id}.json`)}. Follow ${P('04-enrich-recommendation.md')} (TMDB for
poster + overview + canonical year; ratings where available) and ${P('06-relationship-explainer.md')} to make
each relatedTo.why a single vivid, specific sentence. Set each rec's id to "rec-tmdb-<tmdbId>" and cluster to
"${c.id}". Write the enriched JSON array to ${W(`enriched-${c.id}.json`)} and return {"cluster":"${c.id}","count":N}.`,
    { label: `enrich:${c.id}`, phase: 'Enrich',
      schema: { type: 'object', properties: { cluster: { type: 'string' }, count: { type: 'integer' } }, required: ['count'] } }),
)

const enrichedClusters = results.filter(Boolean).map((r, i) => r.cluster || plan[i].id)

// ---- Map: merge recs + lay out the constellation ---------------------------
phase('Map')
const mapped = await agent(
  `Assemble this round's recommendations and build the proximity map.
1) Concatenate every ${W('enriched-*.json')} into one array and write it to ${W('recommendations.json')}
   (these are THIS round's new picks; tag each with round ${A.round || ''} if not already set).
2) Read ${S('ledger.json')} (prior recs with status active/acquired, may be empty) and ${S('library-latest.json')}.
3) Follow ${P('05-compute-proximity.md')} to lay out a map over (a) all recommendations [new + active + acquired]
   and (b) ONLY the library titles those recs relate to (their anchors) — not the whole library. Write
   ${W('map.json')} ({nodes,edges}) and ${W('clusters.json')} (the cluster defs with colors; reuse the
   clusterPlan ids/colors from ${W('taste.json')}).
Return counts.`,
  { label: 'map:layout', phase: 'Map',
    schema: { type: 'object', properties: { recs: { type: 'integer' }, nodes: { type: 'integer' }, edges: { type: 'integer' } }, required: ['recs'] } })

return {
  sampleSize: prep ? prep.sampleSize : 0,
  clusters: plan.map(c => c.label),
  researched: enrichedClusters,
  newRecs: mapped ? mapped.recs : 0,
  mapNodes: mapped ? mapped.nodes : 0,
  note: 'Now run: python3 scripts/build_site.py --workdir ' + WD + ' --append ' + W('recommendations.json'),
}
