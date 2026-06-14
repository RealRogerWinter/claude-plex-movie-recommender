/* ============================================================================
   RecMap — the constellation. A force-directed map where every owned title and
   every recommendation is a node; proximity encodes taste; edges are the
   "because you have X" links. Library = hollow rings, recommendations = glowing
   dots (green = you've since acquired it). Shared by index.html and map.html.
   Depends on d3 v7 (global `d3`). Exposes window.RecMap.
   ========================================================================== */
(function () {
  "use strict";

  function byId(arr) { const m = new Map(); (arr || []).forEach(d => m.set(d.id, d)); return m; }

  // Touch capability, detected at runtime (coarse pointer / touch events present).
  const IS_TOUCH = (typeof window !== "undefined") && (
    ("ontouchstart" in window) ||
    (navigator && navigator.maxTouchPoints > 0) ||
    (window.matchMedia && window.matchMedia("(pointer: coarse)").matches)
  );
  // Honor the OS "reduce motion" / low-power preference in JS too (CSS only stops the keyframes;
  // here we also skip building the ambient starfield entirely so its DOM + layers never exist).
  const REDUCE_MOTION = (typeof window !== "undefined") && window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const RecMap = {
    init(svgSel, data, opts) {
      opts = opts || {};
      const svgEl = document.querySelector(svgSel);
      if (!svgEl || !data || !data.map) return null;

      const lib = byId(data.library);
      const rec = byId(data.recommendations);
      const clusters = byId(data.clusters);
      const colorOf = id => (clusters.get(id) || {}).color || "#8a90a6";
      const item = id => lib.get(id) || rec.get(id);
      const curRound = (data.meta && data.meta.run && data.meta.run.round) || null;

      const rect = svgEl.getBoundingClientRect();
      let W = rect.width || 900, H = rect.height || 600;

      const svg = d3.select(svgEl).attr("viewBox", `0 0 ${W} ${H}`);
      svg.selectAll("*").remove();

      // (No per-node blur filter — SVG feGaussianBlur on many moving poster nodes is a major lag
      // source. A cluster-coloured ring gives the recs prominence far more cheaply.)
      const defs = svg.append("defs");
      // One reusable circular clip so poster <image>s render as circles. Clipped images zoom far
      // better on mobile than SVG pattern fills (which re-rasterize on every pan/zoom).
      defs.append("clipPath").attr("id", "atlas-circ").attr("clipPathUnits", "objectBoundingBox")
        .append("circle").attr("cx", 0.5).attr("cy", 0.5).attr("r", 0.5);

      const root = svg.append("g").attr("class", "atlas-root");

      // Ambient twinkling starfield BEHIND the constellation — sparse small circles whose OPACITY is
      // animated by CSS (compositor-only), so it adds life without any render lag. On touch the count
      // is cut hard and the group-drift + shooting-star streaks are dropped (see app.css + below), since
      // an animating SVG <g> can't composite cleanly on mobile and re-rasterizes the layer every frame.
      // Under prefers-reduced-motion we skip building the starfield DOM entirely.
      const starLayer = svg.insert("g", () => root.node()).attr("class", "atlas-stars").attr("aria-hidden", "true");
      const STAR_CAP = IS_TOUCH ? 14 : 42;
      const STAR_DIV = IS_TOUCH ? 32000 : 16000;
      const starN = REDUCE_MOTION ? 0 : Math.max(IS_TOUCH ? 8 : 18, Math.min(STAR_CAP, Math.round((W * H) / STAR_DIV)));
      starLayer.selectAll("circle")
        .data(d3.range(starN).map(() => ({
          x: Math.random() * W, y: Math.random() * H, r: 0.5 + Math.random() * 1.4,
          dur: (2.5 + Math.random() * 4).toFixed(2), delay: (Math.random() * 5).toFixed(2),
        })))
        .join("circle").attr("class", "atlas-star")
        .attr("cx", s => s.x).attr("cy", s => s.y).attr("r", s => s.r)
        .style("animation-duration", s => s.dur + "s")
        .style("animation-delay", s => "-" + s.delay + "s");

      // A couple of occasional shooting stars — clearly visible motion, but cheap (2 elements,
      // transform + opacity only, mostly idle). Desktop only: on touch their in-group transform
      // animation compounds the star-layer raster cost, so we omit them.
      const shootN = (IS_TOUCH || REDUCE_MOTION) ? 0 : 2;
      starLayer.selectAll("line.shoot").data(d3.range(shootN)).join("line").attr("class", "atlas-shoot")
        .each(function (i) {
          const x = Math.random() * W * 0.6, y = Math.random() * H * 0.5;
          d3.select(this).attr("x1", x).attr("y1", y).attr("x2", x + 22).attr("y2", y + 11)
            .style("animation-delay", (-(i * 5.5) - Math.random() * 3).toFixed(1) + "s");
        });

      // nodes/edges (clone so the sim can mutate)
      let nodes = data.map.nodes.map(n => Object.assign({}, n));
      let nodeIndex = byId(nodes);
      let links = (data.map.edges || [])
        .filter(e => nodeIndex.has(e.source) && nodeIndex.has(e.target))
        .map(e => Object.assign({}, e));

      // Surface EVERYTHING — every recommendation AND every in-library related title — and add
      // connections so the web is dense. No trimming on desktop; a soft cap only on touch for perf.
      // On touch, cap how many recs get the EXPENSIVE poster <image> (the rest read as cluster-coloured
      // dots) rather than DROPPING nodes — this keeps the full hub-and-spoke web, every edge, and every
      // legend/spotlight/cross-talk target intact while cutting the per-frame bitmap cost. `showPoster`
      // is consumed when the <image> layer is appended below; anchors always keep their poster.
      (function rankPosters() {
        // Touch cap bounds the number of poster <image> ELEMENTS (DOM/memory), not render cost — cull()
        // keeps only in-viewport posters displayed and .atlas-moving blanks them during gestures, so the
        // per-frame cost is viewport-bound regardless. 200 gives an append-only ledger plenty of headroom
        // before the lowest-scored tail falls back to dots; raise further if a very large library is smooth.
        const POSTER_CAP = IS_TOUCH ? 200 : Infinity;
        const ranked = nodes.filter(n => n.kind === "rec")
          .sort((a, b) => ((rec.get(b.id) || {}).score || 0) - ((rec.get(a.id) || {}).score || 0));
        ranked.forEach((n, i) => { n.showPoster = i < POSTER_CAP; });
        nodes.filter(n => n.kind !== "rec").forEach(n => { n.showPoster = true; });
      })();

      (function connect() {
        const present = new Set(nodes.map(n => n.id));
        const seen = new Set(links.map(e => (e.source.id || e.source) + "|" + (e.target.id || e.target)));
        const add = (s, t, w) => {
          if (!present.has(s) || !present.has(t) || s === t) return;
          if (seen.has(s + "|" + t) || seen.has(t + "|" + s)) return;
          links.push({ source: s, target: t, weight: w || 0.4 }); seen.add(s + "|" + t);
        };
        // every rec -> each in-library related title it names (spokes to the reference nodes)
        (data.recommendations || []).forEach(r => (r.relatedTo || []).forEach(rel => add(r.id, rel.libraryId, rel.strength || 0.6)));
        // and tie each rec to a few library anchors in its cluster so every neighbourhood connects
        const anchorsByCl = {};
        nodes.filter(n => n.kind !== "rec").forEach(n => { (anchorsByCl[n.cluster] = anchorsByCl[n.cluster] || []).push(n.id); });
        nodes.filter(n => n.kind === "rec").forEach(r => (anchorsByCl[r.cluster] || []).slice(0, 3).forEach(a => add(r.id, a, 0.3)));
      })();

      // Seed positions over a WIDER virtual canvas (bigger than the viewport) so the constellation
      // spreads out; the initial zoom (below) fits the whole thing and the user can zoom in.
      const SPREAD = opts.fullscreen ? 1.5 : 1.9;
      const VW = W * SPREAD, VH = H * SPREAD, pad = 70;
      nodes.forEach(n => {
        n.tx = pad + (n.x != null ? n.x : Math.random()) * (VW - 2 * pad);
        n.ty = pad + (n.y != null ? n.y : Math.random()) * (VH - 2 * pad);
        n.x = n.tx; n.y = n.ty;
        // Inverted sizing: recommendations are the focus (large, poster-filled); the in-library
        // reference titles are smaller. Fixed by kind so the hierarchy stays legible.
        n.rad = n.kind === "rec" ? (opts.fullscreen ? 24 : (IS_TOUCH ? 23 : 19)) : (opts.fullscreen ? 14 : (IS_TOUCH ? 14 : 11));
      });

      const link = root.append("g").attr("stroke-linecap", "round")
        .selectAll("line").data(links).join("line")
        .attr("stroke", d => colorOf((nodeIndex.get(d.source) || {}).cluster))
        .attr("stroke-opacity", 0.22)
        .attr("stroke-width", d => 0.6 + (d.weight || 0.5) * 2.2);

      // Browse-only: nodes are NOT draggable (no repositioning). A press-drag on a node falls through to
      // the SVG's pan/zoom; a tap/click opens its tooltip/card. The layout stays the pre-ticked static one.
      const node = root.append("g").selectAll("g").data(nodes).join("g")
        .attr("cursor", "pointer");

      const hasPoster = d => !!(item(d.id) || {}).poster;
      const ringColor = d => (d.kind === "rec" && statusOf(d) === "acquired") ? "var(--good,#7fd18a)" : colorOf(d.cluster);
      // The map circle is only ~22-48px, so prefer a small dedicated thumbnail (posterMap, emitted by
      // build_site.py) and fall back to the full card poster when no thumb exists. The tooltip still uses
      // the full `poster` so its 52x78 bubble stays crisp.
      const mapPoster = d => { const it = item(d.id) || {}; return it.posterMap || it.poster; };
      const showPosterImg = d => hasPoster(d) && d.showPoster !== false;

      // Poster as a circular CLIPPED IMAGE (top recs + the few reference titles). Clipped images zoom
      // far better on mobile than pattern fills. pointer-events handled by the hit-disc on top.
      // decoding="async" keeps the entrance paint smooth when the static layout draws all at once.
      node.filter(showPosterImg).append("image")
        .attr("href", mapPoster).attr("xlink:href", mapPoster)
        .attr("x", d => -d.rad).attr("y", d => -d.rad)
        .attr("width", d => d.rad * 2).attr("height", d => d.rad * 2)
        .attr("preserveAspectRatio", "xMidYMid slice")
        .attr("decoding", "async")
        .attr("clip-path", "url(#atlas-circ)")
        .style("pointer-events", "none");

      // disc: a cluster-coloured ring around rendered-poster nodes; a filled dot / hollow ring otherwise.
      // Keyed off showPosterImg (not just hasPoster) so a rec whose poster is capped-out on touch still
      // reads as a filled cluster-coloured dot rather than an invisible empty ring. The `--c` custom
      // property feeds the cheap dot proxy shown while panning/zooming/dragging (see app.css .atlas-moving).
      node.append("circle").attr("class", "disc")
        .attr("r", d => d.rad)
        .style("--c", d => colorOf(d.cluster))
        .attr("fill", d => showPosterImg(d) ? "none" : (d.kind === "rec" ? colorOf(d.cluster) : "transparent"))
        .attr("fill-opacity", d => showPosterImg(d) ? 1 : (d.kind === "rec" ? 0.92 : 0))
        .attr("stroke", ringColor)
        .attr("stroke-width", d => d.kind === "rec" ? 3 : 1.8)
        .attr("stroke-opacity", 0.92)
        .style("pointer-events", "none");

      // transparent hit-disc ON TOP captures hover/tap for the whole node interior.
      node.append("circle").attr("class", "hit")
        .attr("r", d => Math.max(d.rad, 11))
        .attr("fill", "transparent").attr("stroke", "none")
        .style("pointer-events", "all");

      // "new this round" cue — a STATIC dashed outer ring (no SMIL animation; an infinite animation
      // on dozens of nodes repaints forever and was a major source of lag).
      node.filter(d => d.kind === "rec" && curRound && (rec.get(d.id) || {}).round === curRound)
        .append("circle").attr("r", d => d.rad + 4).attr("fill", "none")
        .attr("stroke", d => colorOf(d.cluster)).attr("stroke-width", 1.2)
        .attr("stroke-opacity", 0.5).attr("stroke-dasharray", "2 3")
        .style("pointer-events", "none");

      // One-time entrance: edges then nodes fade in as the atlas assembles. A finite transition
      // (opacity only, so it never fights the sim's transform updates) — zero sustained cost.
      link.style("opacity", 0).transition().duration(700).delay(220).style("opacity", 1);
      node.style("opacity", 0).transition().duration(520).delay((d, i) => Math.min(i * 10, 700)).style("opacity", 1);

      function statusOf(d) { const it = rec.get(d.id); return it ? it.status : null; }

      // ---- tooltip --------------------------------------------------------------
      const tip = document.querySelector(opts.tip || "#tip");
      let pinned = null;          // node datum currently pinned (touch)
      let lastTapId = null, lastTapAt = 0;

      // Always render a poster area: real image when present, styled placeholder otherwise,
      // so the bubble is never empty. Poster is a relative path like posters/xxx.jpg.
      function posterHtml(it) {
        const t = (it.title || "").trim();
        const initial = t ? t.charAt(0).toUpperCase() : "·";
        if (it.poster) {
          return `<img class="tt-poster" src="${it.poster}" alt="" ` +
            `onerror="this.classList.add('miss');this.removeAttribute('src');this.style.background='';this.alt='${initial}'">`;
        }
        return `<div class="tt-poster tt-ph">${initial}</div>`;
      }

      function tipHtml(d) {
        const it = item(d.id) || {};
        const isRec = d.kind === "rec";
        const why = isRec && it.relatedTo && it.relatedTo[0] ? it.relatedTo[0].why : (it.overview || "");
        const kindLine = isRec
          ? (statusOf(d) === "acquired" ? "★ in your library" : (it.kind || "recommendation"))
          : "in your library";
        return `<div class="tt">${posterHtml(it)}<div><div class="tt-title">${it.title || d.id}</div>` +
          `<div class="tt-kind">${kindLine} &middot; ${it.year || ""}</div></div></div>` +
          (why ? `<div class="tt-why">${why}</div>` : "") +
          // The "View card" button only on touch: there the tip is PINNED (tappable). On desktop the tip
          // follows the cursor and the button can't be reached — clicking the node itself navigates instead.
          (isRec && IS_TOUCH ? `<button type="button" class="tt-card" data-id="${d.id}">View card &rarr;</button>` : "");
      }

      function placeTip(clientX, clientY) {
        tip.style.left = Math.min(clientX + 16, window.innerWidth - 250) + "px";
        tip.style.top = Math.min(clientY + 16, window.innerHeight - 190) + "px";
      }

      function showTip(ev, d, pin) {
        if (!tip) return;
        tip.innerHTML = tipHtml(d);
        placeTip(ev.clientX, ev.clientY);
        tip.classList.add("show");
        tip.classList.toggle("pinned", !!pin);   // .pinned -> pointer-events: auto (tappable)
        if (pin) pinned = d;
        // wire the in-tip "View card" link (rec nodes only)
        const cardBtn = tip.querySelector(".tt-card");
        if (cardBtn) cardBtn.onclick = (e) => {
          e.stopPropagation();
          hideTip();
          if (opts.onNodeClick) opts.onNodeClick(d);
        };
        if (opts.onNodeHover) opts.onNodeHover(d, true);
      }

      function hideTip() {
        if (!tip) return;
        tip.classList.remove("show", "pinned");
        if (pinned && opts.onNodeHover) opts.onNodeHover(pinned, false);
        pinned = null;
      }

      if (IS_TOUCH) {
        // Touch: a single tap PINS the tooltip near the node (no immediate navigation).
        // Navigation happens via the in-tip "View card" link, or an optional double-tap.
        node.on("click", (ev, d) => {
          ev.stopPropagation();
          const now = Date.now();
          if (lastTapId === d.id && (now - lastTapAt) < 350) {  // double-tap -> navigate
            lastTapId = null; lastTapAt = 0;
            hideTip();
            if (opts.onNodeClick) opts.onNodeClick(d);
            return;
          }
          lastTapId = d.id; lastTapAt = now;
          if (pinned && pinned.id === d.id) { hideTip(); return; }  // tap same node again -> dismiss
          showTip(ev, d, true);
        });
        // Tapping empty space within the map dismisses the pinned tip. Node taps call
        // stopPropagation above, so any click that reaches the svg is on the background.
        svg.on("click.tipdismiss", () => { hideTip(); });
        // Tapping anywhere outside the map and outside the bubble also dismisses it.
        // Passive + capture: never calls preventDefault, so marking it passive lets the browser
        // start scroll/gesture handling without waiting on this handler (it early-outs when nothing
        // is pinned). Tap-to-dismiss behavior is unchanged.
        document.addEventListener("pointerdown", (e) => {
          if (!pinned) return;
          if (tip.contains(e.target)) return;          // taps inside the bubble are fine
          if (svgEl.contains(e.target)) return;        // node / background taps handled above
          hideTip();
        }, { capture: true, passive: true });
      } else {
        // Desktop: hover shows the tip, click navigates (unchanged behavior).
        node.on("mousemove", (ev, d) => { showTip(ev, d, false); })
          .on("mouseleave", () => { hideTip(); })
          .on("click", (ev, d) => { if (opts.onNodeClick) opts.onNodeClick(d); });
      }

      // Layout is computed SYNCHRONOUSLY (pre-ticked off-screen) then drawn ONCE — no animated,
      // continuously re-rendering simulation, which is the biggest mobile lag source. Dragging a
      // node re-runs the sim briefly; otherwise the canvas is static and pan/zoom stays smooth.
      const sim = d3.forceSimulation(nodes)
        .alphaDecay(0.055).velocityDecay(0.45)
        .force("x", d3.forceX(d => d.tx).strength(0.07))   // weak pull -> wider spread
        .force("y", d3.forceY(d => d.ty).strength(0.07))
        .force("charge", d3.forceManyBody().strength(-70).distanceMax(900))  // stronger repulsion
        .force("collide", d3.forceCollide(d => d.rad + 9))                     // more breathing room
        .force("link", d3.forceLink(links).id(d => d.id).distance(d => 70 + (1 - (d.weight || 0.5)) * 55).strength(0.05))
        .stop();
      for (let i = 0; i < 240; i++) sim.tick();   // settle off-screen (no rendering)
      sim.on("tick", ticked);                      // re-render only if the sim runs again (drag)
      ticked();                                    // paint the settled layout once

      function ticked() {
        link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
            .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        node.attr("transform", d => `translate(${d.x},${d.y})`);
      }


      // ---- pan/zoom performance ------------------------------------------------
      // Cached <image> selection (only the nodes that actually render a poster) so culling can flip
      // their display cheaply without disturbing the node/disc/hit selections used by highlight/clear/
      // focusCluster/spotlight or the tooltip wiring.
      const imgSel = node.select("image");

      // While a gesture is active on touch, swap the costly clipped <image> posters for the cheap
      // cluster-coloured discs (a CSS class on the SVG flips display) and promote the moving group to
      // its own compositor layer. Posters come back on a short idle debounce, when culling also runs.
      let moveT = null;
      function setMoving(on) {
        if (on) { clearTimeout(moveT); svgEl.classList.add("atlas-moving"); }
        else {
          clearTimeout(moveT);
          moveT = setTimeout(() => { svgEl.classList.remove("atlas-moving"); cull(); }, 160);
        }
      }

      // Viewport culling: when static, only keep a poster <image> displayed for nodes whose centre is
      // within the (padded) visible view AND whose on-screen radius is big enough to read. Off-screen /
      // tiny posters fall back to their disc. Only the <image> display is toggled — the disc + hit-disc
      // stay put, so tap targets, cross-talk and the legend cover every node unchanged.
      function cull(t) {
        t = t || d3.zoomTransform(svgEl);
        const k = t.k, m = 120 / k;
        const x0 = (-t.x) / k - m, y0 = (-t.y) / k - m;
        const x1 = (W - t.x) / k + m, y1 = (H - t.y) / k + m;
        imgSel.each(function (d) {
          const vis = d.x >= x0 && d.x <= x1 && d.y >= y0 && d.y <= y1 && d.rad * k >= (IS_TOUCH ? 5 : 7);
          this.style.display = vis ? "" : "none";
        });
      }

      // zoom / pan — rAF-coalesced so high-frequency touch-moves write the root transform at most once
      // per frame (d3.zoom keeps its own state; dropping intermediate writes is visually identical).
      let zT = null, zRAF = 0;
      const zoom = d3.zoom().scaleExtent([0.25, 6])
        .on("start", (ev) => { if (IS_TOUCH && ev.sourceEvent) setMoving(true); })
        .on("zoom", ev => {
          zT = ev.transform;
          if (!zRAF) zRAF = requestAnimationFrame(() => { zRAF = 0; root.attr("transform", zT); });
        })
        .on("end", (ev) => { if (IS_TOUCH) { if (ev.sourceEvent) setMoving(false); } else cull(); });
      svg.call(zoom);
      // fit the wider virtual canvas into the viewport initially (the user can zoom in from there)
      const fitS = Math.min(W / VW, H / VH) * 0.98;
      svg.call(zoom.transform, d3.zoomIdentity.translate((W - VW * fitS) / 2, (H - VH * fitS) / 2).scale(fitS));
      cull();   // cull once against the initial fitted transform

      // legend (click a cluster to spotlight it) — selector preserved (#legend by default),
      // whether the element lives inside the map shell (map.html) or below it (index.html).
      const legendEl = document.querySelector(opts.legend || "#legend");
      let spotlight = null;
      if (legendEl) {
        legendEl.innerHTML = "";
        (data.clusters || []).forEach(c => {
          const row = document.createElement("div"); row.className = "lg-row";
          row.innerHTML = `<span class="dot" style="background:${c.color}"></span><span>${c.label}</span>`;
          row.onclick = () => { spotlight = (spotlight === c.id) ? null : c.id; applySpotlight(); };
          legendEl.appendChild(row);
        });
      }
      function applySpotlight() {
        node.transition().duration(250).style("opacity", d => !spotlight || d.cluster === spotlight ? 1 : 0.12);
        link.transition().duration(250).style("opacity", d =>
          !spotlight ? 0.22 : ((nodeIndex.get(d.source.id || d.source) || {}).cluster === spotlight ? 0.35 : 0.03));
      }

      // controller for cross-talk with render.js
      const controller = {
        highlight(id) {
          node.transition().duration(180).style("opacity", d => d.id === id ? 1 : 0.18);
          link.transition().duration(180).style("opacity", d =>
            (d.source.id === id || d.target.id === id) ? 0.6 : 0.04);
        },
        clear() {
          node.transition().duration(180).style("opacity", spotlight ? null : 1);
          applySpotlight();
        },
        focusCluster(id) { spotlight = id; applySpotlight(); },
        sim
      };
      window.__recmap = controller;
      return controller;
    }
  };

  window.RecMap = RecMap;
})();
