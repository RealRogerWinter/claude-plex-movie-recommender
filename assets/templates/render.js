/* ============================================================================
   render.js — turns data.json into the page: hero, the "since last time"
   feedback panel, the cluster-grouped recommendation cards, and the wiring that
   lets the cards and the constellation talk to each other.
   ========================================================================== */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
  const REDUCED = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

  // ---- run / freshness model (shared by the run filter AND the per-card badge) ----------------
  // We PREFER data.meta.runs[] (emitted by build_site.py: distinct rounds, pinned dates+labels) but
  // DERIVE everything from rec.round + rec.proposedAt when it's absent, so old/sample data still works.
  const DAY = 86400000;
  function relativeAge(iso) {
    if (!iso) return "";
    const t = Date.parse(iso); if (isNaN(t)) return "";
    const d = Math.floor((Date.now() - t) / DAY);
    if (d <= 0) return "today";
    if (d === 1) return "yesterday";
    if (d < 7) return d + " days ago";
    if (d < 30) { const w = Math.round(d / 7); return w + (w === 1 ? " week" : " weeks") + " ago"; }
    if (d < 365) { const m = Math.round(d / 30); return m + (m === 1 ? " month" : " months") + " ago"; }
    const y = Math.round(d / 365); return y + (y === 1 ? " year" : " years") + " ago";
  }
  // Build the ordered run list (newest-first) used by the pills, plus a latestRound + a date lookup.
  function buildRunModel(recs, meta) {
    const curRound = meta.run ? meta.run.round : null;
    const declared = Array.isArray(meta.runs) ? meta.runs : null;
    const byRound = new Map();
    (recs || []).forEach(r => {
      const rd = r.round || 0;
      const at = r.proposedAt || "";
      const cur = byRound.get(rd);
      if (!cur) byRound.set(rd, { round: rd, date: at, label: "" });
      else if (at && (!cur.date || at < cur.date)) cur.date = at;   // earliest = the run's date
    });
    let runs;
    if (declared && declared.length) {
      runs = declared.map(d => ({
        round: d.round,
        date: d.date || d.proposedAt || (byRound.get(d.round) || {}).date || "",
        label: d.label || ("Batch " + d.round),
      }));
    } else {
      runs = [...byRound.values()].map(r => ({ round: r.round, date: r.date, label: "Batch " + r.round }));
    }
    runs.sort((a, b) => (b.round || 0) - (a.round || 0));   // newest first
    const latestRound = (curRound != null) ? curRound : (runs[0] ? runs[0].round : null);
    return {
      runs, latestRound, curRound,
      get: rd => runs.find(x => x.round === rd) || byRound.get(rd) || null,
      dateOf: rd => { const r = runs.find(x => x.round === rd) || byRound.get(rd); return r ? r.date : ""; },
    };
  }
  // Per-card freshness: a tier (current | recent | older | acquired) + a label + a relative-age string.
  // Falls back to curRound-only reasoning when the run list is empty (legacy data).
  function freshnessOf(r, model) {
    const runLabel = (model.get(r.round) || {}).label || (r.round != null ? "Batch " + r.round : "");
    if (r.status === "acquired") return { tier: "acquired", runLabel, ageLabel: "" };
    const isLatest = model.latestRound != null && r.round === model.latestRound;
    if (isLatest) return { tier: "current", runLabel, ageLabel: "" };
    // "recent" = the run immediately before the latest in the (newest-first) list
    const i = model.runs.findIndex(x => x.round === r.round);
    const recent = i === 1;
    return { tier: recent ? "recent" : "older", runLabel, ageLabel: relativeAge(model.dateOf(r.round)) };
  }

  const DATA_URL = (new URLSearchParams(location.search)).get("data") || "data.json";

  fetch(DATA_URL).then(r => r.json()).then(render).catch(err => {
    $("#hero-blurb").textContent = "Could not load " + DATA_URL + " — serve over http (python3 scripts/serve.py).";
    console.error(err);
  });

  function render(data) {
    const meta = data.meta || {};
    const clusters = data.clusters || [];
    const colorOf = id => (clusters.find(c => c.id === id) || {}).color || "#8a90a6";
    const curRound = meta.run ? meta.run.round : null;

    // ---- hero ----------------------------------------------------------------
    // Header is static brand (logo + "The Recommendation Atlas") — no per-deploy domain/title in the UI.

    const lib = data.library || [];
    const recsAll = (data.recommendations || []).filter(r => r.status !== "archived");

    // run filter + freshness share one model, built from the LIBRARY recs so the pill set reflects
    // the default view (per-user tabs reuse the same labels; a round a user has no picks in just
    // collapses on their tab). runSel/activePanel live here so a tab switch preserves the selection.
    const runModel = buildRunModel(recsAll, meta);
    let runSel = "all";        // 'all' | 'latest' | '<round>'
    let activePanel = null;    // {host, cards, label, isLibrary} — the currently visible recs panel
    const movies = lib.filter(x => x.type === "movie").length;
    const shows = lib.filter(x => x.type === "show").length;
    const stats = [
      [movies, "films owned"],
      [shows, "shows owned"],
      [recsAll.filter(r => r.status !== "acquired").length, "recommendations"],
    ];
    const statsEl = $("#stats");
    stats.forEach(([n, l]) => { const s = el("div", "stat"); s.append(el("div", "n", esc(n)), el("div", "l", esc(l))); statsEl.append(s); });

    // ---- since last time (the feedback loop made visible) --------------------
    const sl = meta.run && meta.run.sinceLast;
    if (sl && ((sl.added && sl.added.length) || (sl.removed && sl.removed.length) || sl.headline)) {
      $("#since").hidden = false;
      $("#since-headline").textContent = sl.headline || "";
      const chipsEl = $("#since-chips");
      (sl.added || []).forEach(a => {
        const c = el("span", "chip added");
        c.innerHTML = (a.wasRecommended ? '<span class="tick">✓</span>' : "+ ") + esc(a.title) + (a.year ? " <span style='opacity:.6'>(" + esc(a.year) + ")</span>" : "");
        if (a.wasRecommended) c.title = "You took one of our picks — we leaned into it this round.";
        chipsEl.append(c);
      });
      (sl.removed || []).forEach(a => { chipsEl.append(el("span", "chip removed", esc(a.title))); });
    }

    // ---- recommendations grouped by cluster ---------------------------------
    // The cardsById map drives the card<->map cross-talk; it always reflects the
    // LIBRARY view (the map is library-wide and unaffected by per-user tabs).
    const host = $("#clusters");
    const cardsById = new Map();

    // Render one set of recs (grouped by cluster) into a host element. `register`
    // is the per-card sink (used only for the library view, to wire map cross-talk).
    // Each cluster is a horizontal, paginated, swipeable CAROUSEL of the SAME recCards
    // (so card<->map highlight, live Seerr, IMDb/RT links and full descriptions are unchanged).
    function renderClusters(recs, into, register) {
      const active = recs.slice().sort((a, b) => (b.round || 0) - (a.round || 0) || (b.score || 0) - (a.score || 0));
      const byCluster = new Map();
      active.forEach(r => { const k = r.cluster || "cl-other"; (byCluster.get(k) || byCluster.set(k, []).get(k)).push(r); });
      const order = clusters.map(c => c.id).filter(id => byCluster.has(id)).concat([...byCluster.keys()].filter(k => !clusters.find(c => c.id === k)));
      const made = [];
      order.forEach(cid => {
        const list = byCluster.get(cid) || [];
        const cl = clusters.find(c => c.id === cid) || { label: "Other", color: "#8a90a6" };
        const block = el("div", "cluster-block");
        const head = el("div", "cluster-title");
        head.innerHTML = `<span class="swatch" style="background:${cl.color};color:${cl.color}"></span>` +
          `<h3>${esc(cl.label)}</h3><span class="count">${list.length} pick${list.length === 1 ? "" : "s"}</span>`;
        block.append(head);

        const wrap = el("div", "carousel");
        const rail = el("div", "rail");
        rail.setAttribute("role", "list");
        // One IntersectionObserver PER rail (root = this horizontal scroll container) so a card pushed
        // off the right edge still reveals once scrolled into view. This replaces the old page-level
        // reveal IO (root=viewport), which would strand off-screen-right cards at opacity:0 forever.
        const io = new IntersectionObserver((es) => es.forEach((e, i) => {
          if (e.isIntersecting) { setTimeout(() => e.target.classList.add("in"), (i % 8) * 45); io.unobserve(e.target); }
        }), { root: rail, rootMargin: "0px 96px 0px 0px", threshold: 0.12 });

        list.forEach(r => {
          const card = recCard(r, cl, colorOf, curRound, lib, runModel);
          card.setAttribute("role", "listitem");
          rail.append(card); made.push(card); io.observe(card);
          if (register) register(r.id, card);
        });

        const mkNav = (dir, label) => {
          const b = el("button", "car-nav " + dir);
          b.type = "button"; b.setAttribute("aria-label", label); b.tabIndex = -1;
          b.innerHTML = dir === "prev"
            ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>'
            : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>';
          return b;
        };
        const prev = mkNav("prev", "Scroll back"), next = mkNav("next", "Scroll forward");
        wrap.append(el("span", "car-fade left"), el("span", "car-fade right"), prev, rail, next);
        block.append(wrap);
        into.append(block);
        wireCarousel(wrap, rail, prev, next);
      });
      return { count: active.length, cards: made };
    }

    // Library view (default): also feeds the map cross-talk via cardsById.
    const libView = renderClusters(recsAll, host, (id, card) => cardsById.set(id, card));
    activePanel = { host: host, cards: libView.cards, label: "Library", isLibrary: true };
    $("#recs-meta").textContent = libView.count + " picks · newest batch highlighted";

    // ---- per-user tabs -------------------------------------------------------
    // data.users is OPTIONAL. When present & non-empty, show a tab bar atop the
    // recommendations section: "Library" (default, the view above) + one tab per
    // user. Switching swaps ONLY the cards; the map above stays library-wide.
    const users = Array.isArray(data.users) ? data.users.filter(u => u && u.id) : [];
    if (users.length) {
      const tabsEl = $("#rec-tabs");
      tabsEl.hidden = false;
      tabsEl.setAttribute("role", "tablist");
      tabsEl.setAttribute("aria-label", "Whose recommendations to show");
      // a "personalized" framing so the per-user pills read as a prominent control
      if (!document.querySelector(".rec-tabs-kicker")) {
        const k = el("div", "rec-tabs-kicker", "Whose taste?");
        tabsEl.parentNode.insertBefore(k, tabsEl);
      }

      // Each panel owns its own cards host. The library panel reuses the existing
      // #clusters host so its cross-talk wiring stays intact.
      const panels = [{ id: "library", label: "Library", host: host, built: true, cards: libView.cards, count: libView.count }];
      let anchor = host;   // insert each user panel right after the previous one, in order
      users.forEach(u => {
        const ph = el("div", "user-panel");
        ph.hidden = true;
        anchor.parentNode.insertBefore(ph, anchor.nextSibling);
        anchor = ph;
        panels.push({ id: u.id, label: u.label || u.id, host: ph, built: false, recs: (u.recommendations || []), count: (u.recommendations || []).length });
      });

      function selectTab(idx) {
        panels.forEach((p, i) => {
          const on = i === idx;
          p.host.hidden = !on;
          if (p.btn) { p.btn.classList.toggle("active", on); p.btn.setAttribute("aria-selected", on ? "true" : "false"); p.btn.tabIndex = on ? 0 : -1; }
        });
        const p = panels[idx];
        if (!p.built) { const r = renderClusters(p.recs, p.host); p.cards = r.cards; p.count = r.count; p.built = true; }
        refreshStatuses(p.cards);   // live Seerr status when a user tab is shown
        // Reveal is per-rail now (each carousel owns its own IO), uniform across all tabs.
        // Re-apply the active run filter to this (possibly freshly-built) panel and let it own the meta line.
        activePanel = { host: p.host, cards: p.cards, label: idx === 0 ? "Library" : p.label, isLibrary: idx === 0 };
        applyRunFilter(activePanel);
        // Re-render the atlas to match: the library map for "Everyone", or just this user's picks.
        mountMapFor(idx, p.cards, idx === 0 ? "Library" : p.label);
      }

      panels.forEach((p, i) => {
        const isLib = i === 0;
        const icon = isLib
          ? '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/></svg>'
          : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/></svg>';
        const b = el("button", "rec-tab" + (isLib ? " active" : ""));
        b.dataset.kind = isLib ? "library" : "user";
        b.innerHTML = `<span class="rt-ic">${icon}</span><span class="rt-label">${esc(isLib ? "Everyone" : p.label)}</span>` +
          (p.count != null ? `<span class="rt-count">${p.count}</span>` : "");
        b.type = "button";
        b.setAttribute("role", "tab");
        b.setAttribute("aria-selected", i === 0 ? "true" : "false");
        b.tabIndex = i === 0 ? 0 : -1;
        b.addEventListener("click", () => selectTab(i));
        b.addEventListener("keydown", (e) => {
          if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
            e.preventDefault();
            const n = panels.length;
            const next = (i + (e.key === "ArrowRight" ? 1 : n - 1)) % n;
            panels[next].btn.focus(); selectTab(next);
          }
        });
        p.btn = b;
        tabsEl.append(b);
      });
    }

    // ---- run filter (client-side; composes with the tabs) --------------------
    // A pill row in the #recs section-head that filters the VISIBLE recs by the run that produced
    // them — no reload, no re-render: it toggles card.hidden by data-round, collapses now-empty
    // cluster carousels, rewrites their counts, and refreshes each carousel's arrow/fade state.
    function applyRunFilter(panel) {
      if (!panel || !panel.cards) return;
      const matches = card => {
        const rd = Number(card.dataset.round || 0);
        if (runSel === "all") return true;
        if (runSel === "latest") return runModel.latestRound != null && rd === runModel.latestRound;
        return rd === Number(runSel);
      };
      // While an explicit filter is active we force-reveal newly-shown cards (a card hidden before its
      // rail IO ever fired would otherwise be stranded at opacity:0). With 'all' we leave reveal to each
      // rail's IntersectionObserver so the first-paint staggered reveal is preserved.
      const filtering = runSel !== "all";
      let visible = 0;
      panel.cards.forEach(c => {
        const on = matches(c);
        c.hidden = !on;
        // Re-show is instant because we hide via [hidden], never by stripping the `.in` reveal class.
        if (on) { visible++; if (filtering && !c.classList.contains("in")) c.classList.add("in"); }
      });
      panel.host.querySelectorAll(".cluster-block").forEach(block => {
        const cells = [...block.querySelectorAll(".rail > .card")];
        const vis = cells.filter(c => !c.hidden).length;
        block.hidden = vis === 0;
        const cnt = block.querySelector(".cluster-title .count");
        if (cnt) cnt.textContent = vis + " pick" + (vis === 1 ? "" : "s");
        const wrap = block.querySelector(".carousel");
        if (wrap && wrap._carUpdate) wrap._carUpdate();   // scrollWidth changed -> refresh arrows/fades
      });
      const isLib = panel.isLibrary === true;
      const who = isLib ? "" : " for " + panel.label;
      const tail = runSel === "all"
        ? (isLib ? " · newest batch highlighted" : "")
        : runSel === "latest" ? " · latest batch"
        : " · batch " + runSel;
      $("#recs-meta").textContent = visible + " pick" + (visible === 1 ? "" : "s") + who + tail;
    }

    function buildRunFilter() {
      if (runModel.runs.length < 2) return;            // a single-round library doesn't need a filter
      const head = $("#recs .section-head");
      if (!head) return;
      const wrap = el("div", "run-filter");
      wrap.setAttribute("role", "group");
      wrap.setAttribute("aria-label", "Filter recommendations by batch");
      const mk = (sel, label, extra) => {
        const b = el("button", "run-pill" + (sel === runSel ? " active" : "") + (extra || ""));
        b.type = "button"; b.dataset.sel = sel; b.innerHTML = label;
        b.setAttribute("aria-pressed", sel === runSel ? "true" : "false");
        b.addEventListener("click", () => {
          runSel = sel;
          wrap.querySelectorAll(".run-pill").forEach(p => {
            const on = p.dataset.sel === sel;
            p.classList.toggle("active", on); p.setAttribute("aria-pressed", on ? "true" : "false");
          });
          applyRunFilter(activePanel);
          // narrow the atlas to the chosen batch too (re-mount the current tab's map under the filter)
          mountMapFor(currentScopeIdx, activePanel.cards, currentScopeIdx === 0 ? "Library" : activePanel.label);
        });
        return b;
      };
      wrap.append(mk("all", "All batches"));
      wrap.append(mk("latest", "Latest", " is-latest"));
      runModel.runs.forEach(rn => {
        const age = relativeAge(rn.date);
        wrap.append(mk(String(rn.round), "Batch " + esc(rn.round) + (age ? ' <span class="rp-age">' + esc(age) + "</span>" : "")));
      });
      head.append(wrap);
    }
    buildRunFilter();
    applyRunFilter(activePanel);   // harmless when no filter exists (runSel='all' shows everything)

    // ---- footer --------------------------------------------------------------
    $("#footer-note").innerHTML = "Recommendations are cross-checked across recommendation engines, editorial lists, " +
      "community threads and ratings, then tied back to titles you already own. They accumulate run over run — " +
      "what you add tunes what comes next.";
    $("#footer-meta").textContent = "generated " + (meta.generatedAt || "") +
      (curRound ? " · batch " + curRound : "");

    // ---- the map + cross-talk -----------------------------------------------
    // The atlas re-renders to match the selected tab AND the selected batch: "Everyone" shows the
    // library-wide map; a user tab shows only that person's picks; and selecting a batch narrows the
    // map to that batch's recs (+ the titles they anchor to). We re-init RecMap with a scoped data
    // object whenever the tab or the batch filter changes.

    // Same predicate the card filter uses, so the map and the cards always show the same batch.
    function runMatch(round) {
      if (runSel === "all") return true;
      if (runSel === "latest") return runModel.latestRound != null && round === runModel.latestRound;
      return round === Number(runSel);
    }

    // Build a library-wide-shaped data object from one user's recs. Their map isn't pre-computed (the
    // build only lays out the library map), so we derive it from each rec's relatedTo links — always in
    // sync with the ledger. Anchor posters come from user.library (their watch-history basis).
    const PALETTE = ["#8E5BA6", "#4FA3C7", "#C9A227", "#5BA678", "#B5495B", "#E07A3F", "#9d4edd", "#A6452F", "#3f8efc", "#d4a373"];
    function scopeForUser(u) {
      const recs = (u.recommendations || []).filter(r => r.status !== "archived" && runMatch(r.round));
      const defs = new Map((u.clusters || []).map(c => [c.id, c]));
      const ensure = id => {
        if (!id || defs.has(id)) return;
        const label = String(id).replace(/^cl-/, "").replace(/[-_]+/g, " ").replace(/\b\w/g, m => m.toUpperCase());
        let h = 0; for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
        defs.set(id, { id, label, color: PALETTE[h % PALETTE.length] });
      };
      recs.forEach(r => ensure(r.cluster));
      const libById = new Map((u.library || []).map(a => [a.id, a]));   // anchor posters from the basis
      const anchors = new Map();
      recs.forEach(r => (r.relatedTo || []).forEach(rel => {
        const aid = rel.libraryId;
        if (!aid || anchors.has(aid)) return;
        const g = libById.get(aid) || {};
        anchors.set(aid, { id: aid, title: rel.libraryTitle || g.title || aid,
          poster: g.poster || "", posterMap: g.posterMap || g.poster || "", kind: "library", cluster: r.cluster });
      }));
      const anchorArr = [...anchors.values()];
      const nodes = recs.map(r => ({ id: r.id, kind: "rec", cluster: r.cluster }))
        .concat(anchorArr.map(a => ({ id: a.id, kind: "library", cluster: a.cluster })));
      let latest = null; recs.forEach(r => { if (r.round != null && (latest == null || r.round > latest)) latest = r.round; });
      return {
        meta: Object.assign({}, meta, { run: Object.assign({}, meta.run, { round: latest }) }),
        clusters: [...defs.values()],
        library: anchorArr,
        recommendations: recs,
        map: { nodes, edges: [] },    // map.js connect() fills rec->anchor spokes from relatedTo
      };
    }

    // Library scope: the full curated map for "all batches"; otherwise the pre-computed map filtered to
    // the selected batch's recs and the anchors they touch.
    function libraryScope() {
      if (runSel === "all") return data;
      const recs = recsAll.filter(r => runMatch(r.round));
      const keep = new Set(recs.map(r => r.id));
      const anchorIds = new Set();
      recs.forEach(r => (r.relatedTo || []).forEach(rel => rel.libraryId && anchorIds.add(rel.libraryId)));
      const nodes = ((data.map || {}).nodes || []).filter(n => n.kind === "rec" ? keep.has(n.id) : anchorIds.has(n.id));
      const edges = ((data.map || {}).edges || []).filter(e => keep.has(e.source) || keep.has(e.target));
      return { meta, clusters: data.clusters, library: data.library, recommendations: recs, map: { nodes, edges } };
    }

    let currentCtrl = null;
    let activeCardsById = cardsById;        // id -> card for whichever panel the map currently reflects
    let currentScopeIdx = -1, currentScopeRun = null;
    // Mount (or re-mount) the atlas for panel `idx` (0 = library) under the active batch filter.
    function mountMapFor(idx, cards, label) {
      if (idx === currentScopeIdx && runSel === currentScopeRun) return;   // tab + batch unchanged
      currentScopeIdx = idx; currentScopeRun = runSel;
      const scoped = idx === 0 ? libraryScope() : scopeForUser(users[idx - 1]);
      activeCardsById = new Map();
      (cards || []).forEach(c => { if (c.dataset && c.dataset.id) activeCardsById.set(c.dataset.id, c); });
      currentCtrl = window.RecMap && RecMap.init("#map", scoped, {
        legend: "#legend", tip: "#tip",
        onNodeClick: d => { const card = activeCardsById.get(d.id); if (card) flashTo(card); },
        onNodeHover: () => {}
      });
      (cards || []).forEach(card => {
        card.onmouseenter = () => currentCtrl && currentCtrl.highlight(card.dataset.id);
        card.onmouseleave = () => currentCtrl && currentCtrl.clear();
      });
      const scopeEl = $("#map-scope");
      if (scopeEl) scopeEl.textContent = idx === 0 ? "" : "· " + (label || "") + "’s picks";
    }

    mountMapFor(0, libView.cards, "Library");

    // (Staggered reveal is now owned per-rail by each carousel's own IntersectionObserver — uniform
    // across the library and every user tab — so the old page-level reveal IO is gone.)

    // deep-link from the full-screen map ("View card"): ?card=<id> scrolls to + flashes that card
    const focusId = new URLSearchParams(location.search).get("card");
    if (focusId && cardsById.has(focusId)) setTimeout(() => flashTo(cardsById.get(focusId)), 350);

    refreshStatuses([...cardsById.values()]);   // live Seerr status for the default (Library) tab
  }

  // ---- Seerr request / live availability ------------------------------------
  const REQ_KEY = "rec-requested";
  function reqSet() { try { return new Set(JSON.parse(localStorage.getItem(REQ_KEY) || "[]")); } catch (e) { return new Set(); } }
  function reqAdd(id) { try { const s = reqSet(); s.add(id); localStorage.setItem(REQ_KEY, JSON.stringify([...s])); } catch (e) {} }

  // Render a card's action box from a Seerr status code: >=4 in library, >=2 requested, else Request.
  function applyAction(card, code, url) {
    const box = card.querySelector(".actions");
    if (!box) return;
    url = url || card.dataset.seerrUrl || "#";
    if (code >= 4) {
      box.innerHTML = `<a class="req avail" href="${esc(url)}" target="_blank" rel="noopener noreferrer">✓ In your library</a>`;
    } else if (code >= 2) {
      box.innerHTML = `<a class="req pending" href="${esc(url)}" target="_blank" rel="noopener noreferrer">⏳ Requested — view on Seerr ↗</a>`;
    } else {
      box.innerHTML = `<button type="button" class="req request">+ Request</button>`;
      wireRequest(card);
    }
  }

  function wireRequest(card) {
    const btn = card.querySelector("button.req.request");
    if (!btn) return;
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const tmdb = card.dataset.tmdb, mtype = card.dataset.mtype, url = card.dataset.seerrUrl;
      if (!tmdb) { if (url) window.open(url, "_blank", "noopener"); return; }
      btn.disabled = true; btn.textContent = "Requesting…";
      fetch("/api/request", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tmdbId: tmdb, mediaType: mtype }) })
        .then(res => { if (!res.ok) throw 0; reqAdd(card.dataset.id); applyAction(card, 2, url); })
        .catch(() => { if (url) window.open(url, "_blank", "noopener"); btn.disabled = false; btn.textContent = "+ Request"; });
    });
  }

  // On load, ask Seerr (via the proxy) for the LIVE status of these cards and update each — so a
  // reload reflects anything that's since been requested or added to the library.
  function refreshStatuses(cards) {
    const list = (cards || []).filter(c => c.dataset && c.dataset.tmdb);
    if (!list.length) return;
    const items = list.map(c => ({ tmdbId: c.dataset.tmdb, mediaType: c.dataset.mtype }));
    fetch("/api/status", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) })
      .then(r => r.ok ? r.json() : null).then(map => {
        if (!map) return;
        const mine = reqSet();
        list.forEach(c => {
          let code = map[c.dataset.mtype + "-" + c.dataset.tmdb];
          if (code == null) return;
          if (mine.has(c.dataset.id)) code = Math.max(code, 2);  // don't downgrade something you just requested
          applyAction(c, code, c.dataset.seerrUrl);
        });
      }).catch(() => {});
  }

  // ---- carousel: native scroll-snap + paginated arrows; zero per-frame JS --------------------
  // Arrow + edge-fade state recompute ONLY on scroll (rAF-coalesced) and resize — never per frame —
  // matching the mobile-perf ethos. Swipe/momentum is native CSS scrolling. The wrapper exposes
  // `_carUpdate()` so the run filter can refresh arrow/fade state after it hides/shows cards.
  function wireCarousel(wrap, rail, prev, next) {
    const page = () => Math.max(rail.clientWidth - 240, rail.clientWidth * 0.8);   // ~one viewport, keep a card as anchor
    const go = (dir) => rail.scrollBy({ left: dir * page(), top: 0, behavior: REDUCED ? "auto" : "smooth" });
    prev.addEventListener("click", () => go(-1));
    next.addEventListener("click", () => go(1));

    // keyboard paging only when focus is within this carousel (the rail is focusable) so it never
    // hijacks global arrow-key scrolling elsewhere on the page.
    rail.tabIndex = 0;
    wrap.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      go(e.key === "ArrowRight" ? 1 : -1);
    });

    let raf = 0;
    const update = () => {
      raf = 0;
      const max = rail.scrollWidth - rail.clientWidth - 1;
      const x = rail.scrollLeft;
      const overflow = max > 4;            // nothing to page if it all fits
      const atStart = x <= 1, atEnd = x >= max;
      wrap.classList.toggle("has-overflow", overflow);
      wrap.classList.toggle("is-start", !overflow || atStart);
      wrap.classList.toggle("is-end", !overflow || atEnd);
      prev.disabled = !overflow || atStart;
      next.disabled = !overflow || atEnd;
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(update); };
    rail.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    wrap._carUpdate = schedule;            // the run filter calls this after toggling card visibility
    update();
    setTimeout(update, 250);               // recompute once posters lazy-load / fonts settle
  }

  function recCard(r, cl, colorOf, curRound, lib, runModel) {
    const card = el("article", "card"); card.dataset.id = r.id;
    const isNew = curRound && r.round === curRound && r.status !== "acquired";
    const acquired = r.status === "acquired";

    // Freshness: a hook for the run filter (data-round / data-fresh, queried with zero re-render) plus
    // a visible badge + line. The existing acquired/new badge logic is preserved byte-for-byte below.
    const fr = runModel ? freshnessOf(r, runModel) : { tier: isNew ? "current" : "older", runLabel: (r.round != null ? "Batch " + r.round : ""), ageLabel: relativeAge(r.proposedAt) };
    card.dataset.round = r.round || 0;
    card.dataset.fresh = fr.tier;

    const badges = [];
    if (acquired) badges.push('<span class="badge acquired">✓ in your library</span>');
    else if (isNew) badges.push('<span class="badge new">new this batch</span>');
    // older rounds get a quiet "Run N" badge (the newest round already shows the gold "new this round").
    else if (fr.runLabel) badges.push(`<span class="badge run">${esc(fr.runLabel)}</span>`);
    if (r.kind) badges.push(`<span class="badge ${esc(r.kind)}">${esc(r.kind)}</span>`);
    if (r.mode === "daring") badges.push('<span class="badge daring">⚡ daring</span>');
    else if (r.mode === "discovery") badges.push('<span class="badge discovery">✦ discovery</span>');

    const poster = r.poster
      ? `<img src="${esc(r.poster)}" alt="${esc(r.title)} poster" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid'"><div class="ph" style="display:none"><span>${esc(r.title)}</span></div>`
      : `<div class="ph"><span>${esc(r.title)}</span></div>`;

    // Every card links out to IMDb and Rotten Tomatoes (direct by id/url when known, else a precise search).
    const rt = r.ratings || {};
    const q = encodeURIComponent(`${r.title} ${r.year || ""}`.trim());
    const imdbUrl = r.imdbUrl || (r.imdbId ? `https://www.imdb.com/title/${r.imdbId}/` : `https://www.imdb.com/find/?q=${q}&s=tt`);
    const rtUrl = r.rtUrl || `https://www.rottentomatoes.com/search?search=${encodeURIComponent(r.title)}`;
    const links = [
      `<a class="ext imdb" href="${imdbUrl}" target="_blank" rel="noopener noreferrer">IMDb${rt.imdb ? " <b>" + esc(rt.imdb) + "</b>" : ""} ↗</a>`,
      `<a class="ext rt" href="${rtUrl}" target="_blank" rel="noopener noreferrer">RT${rt.rt ? " <b>" + esc(rt.rt) + "</b>" : ""} ↗</a>`,
    ];
    if (rt.letterboxd) links.push(`<a class="ext lb" href="https://letterboxd.com/search/films/${encodeURIComponent(r.title)}/" target="_blank" rel="noopener noreferrer">LB <b>${esc(rt.letterboxd)}</b> ↗</a>`);

    const rels = (r.relatedTo || []).map(rel =>
      `<div class="rel-item"><span class="lt">${esc(rel.libraryTitle || "your library")}</span>` +
      (rel.why ? `<div class="why">${esc(rel.why)}</div>` : "") + `</div>`).join("");

    // data attrs let the on-load live refresh map this card to its Seerr media + request URL
    const tmdbId = r.tmdbId || (typeof r.id === "string" && r.id.indexOf("rec-tmdb-") === 0 ? r.id.slice(9) : "");
    if (tmdbId) card.dataset.tmdb = tmdbId;
    card.dataset.mtype = r.type === "show" ? "tv" : "movie";
    if (r.seerr && r.seerr.url) card.dataset.seerrUrl = r.seerr.url;

    // Freshness line: always shows the run + relative age ("Run 2 · 3 days ago"); the newest run glows gold.
    const isLatestCard = fr.tier === "current";
    const freshText = (isLatestCard ? "Latest batch" : (fr.runLabel || "Batch " + (r.round || "?"))) + (fr.ageLabel ? " · " + fr.ageLabel : "");
    const freshness = `<div class="freshness${isLatestCard ? " is-latest" : ""}"><span class="fr-dot"></span>${esc(freshText)}</div>`;

    card.innerHTML =
      `<div class="poster">${poster}<div class="badges">${badges.join("")}</div></div>` +
      `<div class="card-body">` +
        `<h4>${esc(r.title)}</h4><div class="yr">${esc(r.year || "")}${r.runtime ? " · " + esc(r.runtime) : ""}</div>` +
        freshness +
        `<div class="ratings">${links.join("")}</div>` +
        (r.overview ? `<p class="overview">${esc(r.overview)}</p>` : "") +
        (rels ? `<div class="rel"><div class="rl">because you have</div>${rels}</div>` : "") +
        `<div class="actions"></div>` +
      `</div>`;

    // Optimistic initial action (your prior requests + the build-time status); the on-load
    // refreshStatuses() then corrects it live from Seerr.
    const baked = (r.seerr || {}).statusCode || 0;
    applyAction(card, reqSet().has(r.id) ? Math.max(2, baked) : baked, (r.seerr || {}).url);
    return card;
  }

  function flashTo(card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
  }
})();
