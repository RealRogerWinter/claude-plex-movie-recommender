#!/usr/bin/env python3
"""Final stage — assemble data.json and build the static site.

Two modes:
  * render-only:  build_site.py --data path/to/data.json --out site
      Renders an already-assembled data file (used for the sample and for quick checks).
  * assemble:     build_site.py --workdir ~/recommendations --append work/recommendations.json
      Merges this round's NEW recommendations into the ledger (deduping against owned +
      prior picks), assembles data.json from the WHOLE ledger + current library + clusters
      + map + diff, then builds.

Either way it: downloads every poster locally (so the published site is self-contained and
never leaks the Plex token), copies the templates, stamps meta, and — in assemble mode —
rotates the snapshot so the next run has something to diff against.
"""
import argparse
import datetime
import os
import shutil
import subprocess
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plexlib as P  # noqa: E402
import config as C  # noqa: E402
import seerr  # noqa: E402
from scan_library import slug  # noqa: E402  (shared username -> subdir slug)

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DEFAULT = os.path.join(SKILL_DIR, "assets", "templates")
TEMPLATE_FILES = ["index.html", "map.html", "app.css", "render.js", "map.js", "favicon.svg", "logo.svg", "og.svg"]
VERSIONED_ASSETS = ("app.css", "render.js", "map.js")
D3_CDN = "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"


def slim_lib(i):
    """Keep only what the site/map need; drop internal Plex fields (summary, ratingKey, section)."""
    return {k: i[k] for k in ("id", "title", "type", "year", "genres", "director", "poster", "cluster", "themes")
            if k in i}


def headline(diff, new_count):
    if not diff or diff.get("isFirstRun"):
        return ""
    a = diff["counts"]["added"]
    acq = diff["counts"]["acquired"]
    if a == 0 and acq == 0:
        bits = []
    else:
        s = f"You added {a} title{'s' if a != 1 else ''} since last time"
        if acq:
            s += f" — {acq} {'was' if acq == 1 else 'were'} one of our picks ✓"
        bits = [s + "."]
    bits.append(f"{new_count} fresh recommendation{'s' if new_count != 1 else ''} this round.")
    return " ".join(bits).strip()


def _run_label(rnd, iso):
    """Human label like "Batch 3 · Jun 14"; tolerate a missing/garbage date."""
    mon = ""
    try:
        d = datetime.date.fromisoformat(iso)
        # %-d is glibc-only; fall back to a date-less label if it isn't supported
        mon = d.strftime("%b %-d")
    except Exception:  # noqa: BLE001
        mon = ""
    return f"Batch {rnd}" + (f" · {mon}" if mon else "")


def build_runs(recs, runs_log, cur_round):
    """Ordered list of the DISTINCT rounds present across recs, each with a pinned
    date + label + count + isCurrent. Oldest -> newest.

    `runs_log` is the persistent state/runs.json (mutated in place); pass {} in
    render-only mode (no workdir) and nothing is persisted. A round's representative
    date is the EARLIEST proposedAt among its recs (the run's "birthday"); it is
    pinned the FIRST time the round is seen so a later rebuild can never shift an
    older run's label even if the ledger is hand-edited."""
    by_round = {}
    for r in recs:
        rnd = r.get("round")
        if rnd is None:
            continue
        b = by_round.setdefault(rnd, {"count": 0, "earliest": None, "modes": {}})
        b["count"] += 1
        pa = r.get("proposedAt") or ""
        if pa and (b["earliest"] is None or pa < b["earliest"]):
            b["earliest"] = pa
        md = r.get("mode") or ""
        if md:
            b["modes"][md] = b["modes"].get(md, 0) + 1
    out = []
    for rnd in sorted(by_round):
        info = by_round[rnd]
        key = str(rnd)
        mode = max(info["modes"], key=info["modes"].get) if info["modes"] else ""
        pinned = runs_log.get(key) or {}
        date = pinned.get("date") or info["earliest"] or ""
        if key in runs_log:                     # pin once; never overwrite an older run's label
            label = pinned.get("label") or _run_label(rnd, date)
        else:
            label = _run_label(rnd, date) + (" · " + mode[:1].upper() + mode[1:] if mode else "")
            runs_log[key] = {"date": date, "label": label}
        out.append({"round": rnd, "label": label, "date": date, "mode": mode,
                    "count": info["count"], "isCurrent": rnd == cur_round})
    return out


def merge_new_recs(ledger, new_recs, owned_keys, nxt_round, mode=""):
    have = {P.make_key(e["title"], e.get("year"), e["type"]) for e in ledger}
    added = 0
    for r in new_recs:
        k = P.make_key(r["title"], r.get("year"), r["type"])
        if k in owned_keys or k in have:
            continue  # safety net: never re-propose owned or already-listed titles
        r.setdefault("id", "rec-" + k.replace("|", "-").replace(" ", "-")[:48])
        # This append IS round `nxt_round` by definition (track_state's diff round). Assign it
        # unconditionally — the pipeline's map stage can bake an unreliable `round` into each rec
        # (it varies by run), so trusting that would mislabel/collide rounds. nxt_round is authoritative.
        r["round"] = nxt_round
        r["status"] = "active"
        r.setdefault("proposedAt", P.today())
        if mode:
            r["mode"] = mode          # "daring" | "discovery" — tags the run that produced this pick
        ledger.append(r)
        have.add(k)
        added += 1
    return added


def _name_map(cfg):
    """slug -> friendly name, from library.tautulli.users when it's an explicit list."""
    users = C.get(cfg, "library.tautulli.users", "all")
    if isinstance(users, list):
        return {slug(n): n for n in users if n}
    return {}


def build_users(workdir, cfg):
    """Collect each per-user ledger under <workdir>/users/<slug>/ into the data["users"] array.

    For every users/<slug>/ that has state/ledger.json, emit
        { id: "u-<slug>", label: <friendly name if known else slug>,
          recommendations: [ledger entries with status active|acquired] }
    Recommendations keep the SAME shape as the main library-wide recs (the ledger entries already
    carry the full rec schema), so the frontend renders them identically."""
    users_dir = os.path.join(workdir, "users")
    if not os.path.isdir(users_dir):
        return []
    names = _name_map(cfg)
    out = []
    for sl in sorted(os.listdir(users_dir)):
        ledger_path = os.path.join(users_dir, sl, "state", "ledger.json")
        if not os.path.exists(ledger_path):
            continue
        ledger = P.load_json(ledger_path, []) or []
        recs = [e for e in ledger if e.get("status") in ("active", "acquired")]
        # Cluster defs for this user (id/label/color), so the per-user atlas can colour nodes and
        # build its legend. The last pipeline run's map stage lays out the whole ledger, so its
        # clusters.json covers every cluster the user's recs reference. The frontend also synthesizes
        # a fallback def for any cluster id not found here, so a missing/partial file degrades gracefully.
        clusters = P.load_json(os.path.join(users_dir, sl, "work", "clusters.json"), []) or []
        # Anchor metadata for the per-user atlas: the user's recs anchor to titles in their watch-history
        # basis (relatedTo.libraryId == an id in library-latest.json). Resolve those so the in-library
        # nodes on their atlas render real posters instead of bare rings (poster downloaded below).
        basis = P.load_json(os.path.join(users_dir, sl, "state", "library-latest.json"), []) or []
        basis_by_id = {b.get("id"): b for b in basis}
        ref_ids = set()
        for e in recs:
            for rel in (e.get("relatedTo") or []):
                if isinstance(rel, dict) and rel.get("libraryId"):
                    ref_ids.add(rel["libraryId"])
        user_lib = [{"id": aid, "title": basis_by_id[aid].get("title", ""),
                     "type": basis_by_id[aid].get("type", "movie"),
                     "poster": basis_by_id[aid].get("poster", ""),
                     "year": basis_by_id[aid].get("year", "")}
                    for aid in ref_ids if aid in basis_by_id]
        out.append({"id": "u-" + sl, "label": names.get(sl, sl),
                    "recommendations": recs, "clusters": clusters, "library": user_lib})
    return out


def resolve_posters(data, out, token, base, skip):
    """Download posters only for what's actually shown — every recommendation plus the
    library titles that appear as anchors on the map. Other (non-displayed) library items
    get their poster blanked so a Plex/LAN path with the token never reaches the site."""
    shown = {n["id"] for n in data.get("map", {}).get("nodes", [])}
    shown |= {r["id"] for r in data.get("recommendations", [])}
    pdir = os.path.join(out, "posters")
    cache = {}  # id -> (poster, posterMap) so a poster shared across tabs downloads once

    # The map renders each title in a ~22-48px circle, so it gets a dedicated tiny thumbnail separate
    # from the full-bleed card poster: TMDB drops to w185, Plex thumbs go through Plex's own transcode
    # at width=96. ~10-25x less decode/GPU work per node with no visible change at map size; the card
    # and the tooltip keep using the full `poster`.
    def tmdb_map(src):
        return src.replace("/t/p/w500", "/t/p/w185").replace("/t/p/w342", "/t/p/w185")

    def plex_map(src):
        q = urllib.parse.quote(src, safe="")
        return f"/photo/:/transcode?width=96&height=144&minSize=1&upscale=0&url={q}"

    def fetch(item):
        src = item.get("poster") or ""
        if src.startswith("posters/"):
            return                         # already a local relative path
        if item["id"] in cache:
            item["poster"], item["posterMap"] = cache[item["id"]]
            return
        dest = os.path.join(pdir, f"{item['id']}.jpg")
        mdest = os.path.join(pdir, f"{item['id']}.map.jpg")
        # disk cache: reuse a poster already downloaded on a prior build (big speedup on rebuilds,
        # and spares Plex/TMDB from being re-hit every time).
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            poster = f"posters/{item['id']}.jpg"
            poster_map = (f"posters/{item['id']}.map.jpg"
                          if (os.path.exists(mdest) and os.path.getsize(mdest) > 0) else poster)
            item["poster"], item["posterMap"] = poster, poster_map
            cache[item["id"]] = (poster, poster_map)
            return
        okm = False
        if src.startswith("/"):            # Plex thumb path -> base + token (token stripped on save)
            ok = P.download(f"{base}{src}", dest, token=token)
            # small map thumb via Plex transcode; fall back to the full thumb if transcode is unavailable
            okm = P.download(f"{base}{plex_map(src)}", mdest, token=token)
        elif src.startswith("http"):
            if "image.tmdb.org/t/p/w500" in src:   # smaller poster -> lighter card (was also used by map)
                src = src.replace("/t/p/w500", "/t/p/w342")
            ok = P.download(src, dest)
            if ok:
                okm = P.download(tmdb_map(src), mdest)
        else:
            ok = False
        poster = f"posters/{item['id']}.jpg" if ok else ""
        # posterMap: prefer the dedicated tiny thumb, else fall back to the full poster so the map
        # circle is never blank when a transcode/resize fails.
        poster_map = f"posters/{item['id']}.map.jpg" if okm else poster
        item["poster"], item["posterMap"] = poster, poster_map
        cache[item["id"]] = (poster, poster_map)

    for item in data.get("library", []) + data.get("recommendations", []):
        if item.get("poster", "").startswith("posters/"):
            continue                       # already a local relative path
        if skip or item["id"] not in shown or not item.get("poster"):
            item["poster"] = ""            # not displayed (or skipped): blank any LAN/Plex path
            continue
        fetch(item)

    # Per-user recommendation cards are always shown when their tab is active -> fetch their posters
    # too (deduped via the cache when an id is shared with a library-wide pick). Same for each user's
    # anchor titles (their atlas's in-library nodes), so those render real posters, not bare rings.
    for u in data.get("users", []):
        for item in u.get("recommendations", []) + u.get("library", []):
            if skip or not item.get("poster"):
                item["poster"] = "" if not item.get("poster", "").startswith("posters/") else item["poster"]
                continue
            fetch(item)


def rasterize_og(out):
    """Emit a 1200x630 og.png from og.svg for social cards (Twitter/Facebook/LinkedIn don't render SVG
    og:images). Uses whatever rasterizer is on PATH; returns "og.png" on success, else None so the caller
    falls back to the SVG. Never fails the build."""
    src, dst = os.path.join(out, "og.svg"), os.path.join(out, "og.png")
    if not os.path.exists(src):
        return None
    if shutil.which("rsvg-convert"):
        cmd = ["rsvg-convert", "-w", "1200", "-h", "630", src, "-o", dst]
    elif shutil.which("inkscape"):
        cmd = ["inkscape", src, "--export-type=png", "-w", "1200", "-h", "630", "-o", dst]
    elif shutil.which("convert"):  # ImageMagick
        cmd = ["convert", "-background", "none", "-density", "144", src, "-resize", "1200x630", dst]
    else:
        return None
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        return "og.png" if (os.path.exists(dst) and os.path.getsize(dst) > 0) else None
    except Exception:  # noqa: BLE001
        return None


def assemble(args, cfg):
    state = os.path.join(args.workdir, "state")
    work = os.path.join(args.workdir, "work")
    library = P.load_json(args.library or os.path.join(work, "library.json")) \
        or P.load_json(os.path.join(state, "library-latest.json"), [])
    library = [slim_lib(i) for i in library]
    ledger = P.load_json(os.path.join(state, "ledger.json"), [])
    diff = P.load_json(os.path.join(work, "diff.json"), {})
    nxt_round = (diff or {}).get("round", 1)
    owned_keys = {P.make_key(i["title"], i.get("year"), i["type"]) for i in library}

    if args.append:
        new_recs = P.load_json(args.append, [])
        n = merge_new_recs(ledger, new_recs, owned_keys, nxt_round, getattr(args, "mode", "") or "")
        P.write_json(os.path.join(state, "ledger.json"), ledger)
        print(f"Merged {n} new recommendations into the ledger (round {nxt_round}).")

    recs = [e for e in ledger if e.get("status") in ("active", "acquired")]
    clusters = P.load_json(args.clusters or os.path.join(work, "clusters.json"), [])
    mapdata = P.load_json(args.map or os.path.join(work, "map.json"), {"nodes": [], "edges": []})
    prefs = P.load_json(os.path.join(state, "preferences.json")) or P.load_json(os.path.join(work, "taste.json"), {})
    blurb = (prefs or {}).get("tasteSummary", "")

    new_count = sum(1 for r in recs if r.get("round") == nxt_round and r.get("status") == "active")
    data = {
        "meta": {
            "libraryTitle": args.title,
            "run": {
                "round": nxt_round,
                "previousRunAt": (diff or {}).get("previousRunAt", ""),
                "sinceLast": {
                    "added": (diff or {}).get("added", []),
                    "removed": (diff or {}).get("removed", []),
                    "acquiredFromRecs": (diff or {}).get("acquiredFromRecs", []),
                    "headline": headline(diff, new_count),
                },
            },
        },
        "clusters": clusters,
        "library": library,
        "recommendations": recs,
        "map": mapdata,
    }

    # meta.runs: the distinct rounds present in the ledger, with pinned dates+labels (state/runs.json).
    # Additive — the frontend falls back to round===meta.run.round when this is absent.
    runs_log = P.load_json(os.path.join(state, "runs.json"), {}) or {}
    data["meta"]["runs"] = build_runs(recs, runs_log, nxt_round)
    P.write_json(os.path.join(state, "runs.json"), runs_log)

    # Per-user recommendations (optional). The library-wide recs + map above are UNAFFECTED;
    # this only adds a parallel data["users"] array that the frontend surfaces as extra tabs.
    if C.get(cfg, "personal_recommendations", False):
        users = build_users(args.workdir, cfg)
        if users:
            data["users"] = users
            print(f"Folded {len(users)} user tab(s): "
                  + ", ".join(f"{u['label']} ({len(u['recommendations'])})" for u in users))
    return data


def rotate(args):
    state = os.path.join(args.workdir, "state")
    latest = os.path.join(state, "library-latest.json")
    if os.path.exists(latest):
        shutil.copy2(latest, os.path.join(state, "library-previous.json"))
    run = P.load_json(os.path.join(args.workdir, "work", "diff.json"), {}) or {}
    P.write_json(os.path.join(state, "last-run.json"), {"date": P.today(), "round": run.get("round", 1)})
    # archive this run
    stamp = P.now_stamp()
    rundir = os.path.join(state, "runs", stamp)
    for f in ("library-latest.json",):
        if os.path.exists(os.path.join(state, f)):
            P.write_json(os.path.join(rundir, "library.json"), P.load_json(os.path.join(state, f), []))
    for f in ("diff.json",):
        src = os.path.join(args.workdir, "work", f)
        if os.path.exists(src):
            P.write_json(os.path.join(rundir, f), P.load_json(src, {}))


def main():
    ap = argparse.ArgumentParser(description="Assemble data.json and build the static site.")
    ap.add_argument("--config")
    ap.add_argument("--workdir")
    ap.add_argument("--data", help="render-only: an already-assembled data.json")
    ap.add_argument("--append", help="assemble: new recommendations json to merge into the ledger")
    ap.add_argument("--mode", default="", help="tag this round's merged recs: daring | discovery")
    ap.add_argument("--library"); ap.add_argument("--clusters"); ap.add_argument("--map")
    ap.add_argument("--out", default=None)
    ap.add_argument("--templates", default=TEMPLATES_DEFAULT)
    ap.add_argument("--base-url")
    ap.add_argument("--prefs")
    ap.add_argument("--title")
    ap.add_argument("--vendor", action="store_true", help="download D3 locally instead of CDN")
    ap.add_argument("--no-posters", action="store_true")
    args = ap.parse_args()

    cfg = C.load(args.config)
    args.workdir = args.workdir or cfg["workdir"]
    args.base_url = args.base_url or C.get(cfg, "library.plex.base_url", P.DEFAULT_BASE)
    args.prefs = args.prefs or C.get(cfg, "library.plex.prefs_path", P.DEFAULT_PREFS)
    args.title = args.title or C.get(cfg, "site.title", "My Recommendation Atlas")
    tagline = C.get(cfg, "site.tagline", "")
    # Absolute base URL for OpenGraph/social tags (scrapers need absolute image/url). From deploy.domain;
    # falls back to root-relative ("/og.svg") when no domain is configured.
    site_domain = (C.get(cfg, "deploy.domain", "") or "").strip().strip("/")
    site_url = ("https://" + site_domain) if site_domain else ""

    out = args.out or os.path.join(args.workdir, "site")
    os.makedirs(out, exist_ok=True)

    if args.data:
        data = P.load_json(args.data)
        if data is None:
            print(f"ERROR: could not read {args.data}", file=sys.stderr); sys.exit(1)
        data.setdefault("meta", {})["libraryTitle"] = data["meta"].get("libraryTitle", args.title)
        # render-only has no workdir/ledger: synthesize meta.runs in-memory (no runs.json write) so the
        # sample/old data files still gain the field; an already-present meta.runs is left untouched.
        m0 = data["meta"]
        if "runs" not in m0 and data.get("recommendations"):
            cur = (m0.get("run") or {}).get("round")
            m0["runs"] = build_runs(data["recommendations"], {}, cur)
    else:
        data = assemble(args, cfg)

    # stamp meta
    m = data.setdefault("meta", {})
    m["generatedAt"] = P.today()
    if tagline:
        m.setdefault("tagline", tagline)
    m["counts"] = {"library": len(data.get("library", [])),
                   "recommendations": len(data.get("recommendations", [])),
                   "clusters": len(data.get("clusters", []))}

    # Seerr: real availability lookups + request deep-links (read-only; reuses Seerr's auth for requests).
    scfg = C.get(cfg, "services.seerr", {}) or {}
    if scfg.get("enabled"):
        skey = seerr.read_key(scfg.get("container", "seerr"), scfg.get("settings_path", "/app/config/settings.json"))
        sbase = scfg.get("base_url", "http://localhost:5055")
        spub = scfg.get("public_url", "")
        avail, checked = seerr.annotate(data, sbase, spub, skey)
        # annotate each user's recommendations with the same Seerr service
        for u in data.get("users", []):
            ua, uc = seerr.annotate({"recommendations": u.get("recommendations", [])}, sbase, spub, skey)
            avail += ua; checked += uc
        print(f"Seerr: checked {checked} recs · {avail} already in your library")

    token = None if args.no_posters else P.read_plex_token(args.prefs)
    resolve_posters(data, out, token, args.base_url, args.no_posters)

    for fn in TEMPLATE_FILES:
        src = os.path.join(args.templates, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, fn))

    if args.vendor:
        if P.download(D3_CDN, os.path.join(out, "vendor", "d3.v7.min.js")):
            for fn in ("index.html", "map.html"):
                p = os.path.join(out, fn)
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        html = f.read()
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(html.replace(D3_CDN, "vendor/d3.v7.min.js"))

    # Cache-bust local JS/CSS so a CDN/edge (e.g. Cloudflare) can't serve a stale asset against
    # fresh HTML after a rebuild — a version mismatch there breaks rendering.
    og_image = rasterize_og(out) or "og.svg"   # PNG card when a rasterizer is available, else the SVG
    ver = str(int(time.time()))
    for fn in ("index.html", "map.html"):
        p = os.path.join(out, fn)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                html = f.read()
            for asset in VERSIONED_ASSETS:
                html = html.replace('"' + asset + '"', '"' + asset + '?v=' + ver + '"')
            html = html.replace("__SITE_URL__", site_url)   # absolute OG/social URLs from deploy.domain
            html = html.replace("__OG_IMAGE__", og_image)   # og.png when rasterized, else og.svg
            with open(p, "w", encoding="utf-8") as f:
                f.write(html)

    P.write_json(os.path.join(out, "data.json"), data)

    if not args.data:  # assemble mode advances the snapshot for next time
        rotate(args)

    print(f"Built site -> {out}")
    print(f"  {m['counts']['library']} library · {m['counts']['recommendations']} recs · {m['counts']['clusters']} clusters")
    print(f"Preview: python3 {os.path.join('scripts','serve.py')} --dir {out}")


if __name__ == "__main__":
    main()
