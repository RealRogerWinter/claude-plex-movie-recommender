#!/usr/bin/env python3
"""Compare recommendation runs by mode (standard / daring / discovery) within a
built data.json, across the library tab and every per-user tab.

This is the feedback-loop's measurement tool: after a daring/discovery pass, run
it to see whether the bold/novel picks actually behaved differently from the
standard run, and where they fell short — so the prompts can be tuned from data
rather than vibes. Reports, per (target, mode): count, Seerr availability,
enrichment health (poster/overview/relatedTo/sources coverage), year & rating
profile, cluster spread, and which library anchors each mode leans on (low
overlap with the standard run = it explored genuinely new shelves).

Usage:
  python3 scripts/analyze_runs.py                 # uses <workdir>/site/data.json from config
  python3 scripts/analyze_runs.py path/to/data.json
  python3 scripts/analyze_runs.py --workdir ~/recommendations
"""
import argparse
import json
import os
import sys
import statistics as st
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C  # noqa: E402


def J(x, default):
    """Fields like ratings/relatedTo/sources/seerr may be JSON strings OR already
    parsed — normalize both, and never blow up on a malformed value."""
    if isinstance(x, str):
        try:
            return json.loads(x) if x.strip() else default
        except Exception:
            return default
    return x if x is not None else default


def imdb_of(rec):
    r = J(rec.get("ratings"), {})
    v = (r or {}).get("imdb", "") if isinstance(r, dict) else ""
    try:
        return float(v)
    except Exception:
        return None


def yr(rec):
    try:
        return int(str(rec.get("year", ""))[:4])
    except Exception:
        return None


def mode_of(rec):
    return rec.get("mode") or "standard"


def anchors(rec):
    return [a.get("libraryTitle") for a in J(rec.get("relatedTo"), []) if a.get("libraryTitle")]


def pct(n, d):
    return f"{100*n/d:4.0f}%" if d else "  — "


def analyze(target, recs):
    recs = [r for r in recs if r.get("status", "active") == "active"]
    if not recs:
        return
    by_mode = defaultdict(list)
    for r in recs:
        by_mode[mode_of(r)].append(r)

    print(f"\n{'='*78}\n {target}  —  {len(recs)} active recs across {len(by_mode)} mode(s)\n{'='*78}")
    header = (f"{'mode':<11}{'n':>4}{'avail':>7}{'poster':>8}{'overvw':>7}{'related':>8}"
              f"{'src≥2':>7}{'medYr':>7}{'pre80':>7}{'imdb':>6}{'noIMDb':>7}{'clusters':>9}")
    print(header)
    print("-" * len(header))
    anchor_sets = {}
    for mode in ("standard", "daring", "discovery"):
        rs = by_mode.get(mode)
        if not rs:
            continue
        n = len(rs)
        avail = sum(1 for r in rs if (J(r.get("seerr"), {}) or {}).get("statusCode") == 5)
        poster = sum(1 for r in rs if str(r.get("poster", "")).startswith("posters/"))
        overvw = sum(1 for r in rs if (r.get("overview") or "").strip())
        related = sum(1 for r in rs if anchors(r))
        src2 = sum(1 for r in rs if len(J(r.get("sources"), [])) >= 2)
        years = [y for y in (yr(r) for r in rs) if y]
        pre80 = sum(1 for y in years if y < 1980)
        imdbs = [v for v in (imdb_of(r) for r in rs) if v is not None]
        noimdb = n - len(imdbs)
        clusters = len({r.get("cluster") for r in rs})
        anchor_sets[mode] = Counter(a for r in rs for a in anchors(r))
        print(f"{mode:<11}{n:>4}{pct(avail,n):>7}{pct(poster,n):>8}{pct(overvw,n):>7}"
              f"{pct(related,n):>8}{pct(src2,n):>7}"
              f"{(st.median(years) if years else 0):>7.0f}{pct(pre80,len(years)):>7}"
              f"{(st.mean(imdbs) if imdbs else 0):>6.1f}{pct(noimdb,n):>7}{clusters:>9}")

    # Anchor novelty: how much do daring/discovery reuse the SAME library anchors the
    # standard run already leaned on? Low overlap = exploring new shelves (the goal).
    base = set(anchor_sets.get("standard", {}))
    for mode in ("daring", "discovery"):
        s = set(anchor_sets.get(mode, {}))
        if not s:
            continue
        overlap = len(s & base) / len(s) if s else 0
        fresh = sorted(s - base)
        print(f"  ↳ {mode}: anchors to {len(s)} library titles, "
              f"{100*overlap:.0f}% also used by standard; {len(fresh)} NEW anchor(s)"
              + (f" e.g. {', '.join(fresh[:5])}" if fresh else ""))

    # Thin picks: anything missing a poster, overview, anchor, or triangulation.
    thin = []
    for r in recs:
        miss = []
        if not str(r.get("poster", "")).startswith("posters/"):
            miss.append("poster")
        if not (r.get("overview") or "").strip():
            miss.append("overview")
        if not anchors(r):
            miss.append("anchor")
        if len(J(r.get("sources"), [])) < 2:
            miss.append("1-source")
        if miss:
            thin.append(f"    [{mode_of(r):<9}] {r.get('title')} ({r.get('year')}) — missing: {', '.join(miss)}")
    if thin:
        print(f"  ⚠ {len(thin)} thin pick(s):")
        print("\n".join(thin[:25]))
        if len(thin) > 25:
            print(f"    … +{len(thin)-25} more")


def main():
    ap = argparse.ArgumentParser(description="Compare recommendation runs by mode within a data.json.")
    ap.add_argument("data", nargs="?", help="path to a built data.json (default: <workdir>/site/data.json)")
    ap.add_argument("--config")
    ap.add_argument("--workdir")
    args = ap.parse_args()

    path = args.data
    if not path:
        cfg = C.load(args.config)
        workdir = args.workdir or cfg["workdir"]
        path = os.path.join(workdir, "site", "data.json")
    if not os.path.exists(path):
        sys.exit(f"data.json not found: {path}  (build the site first, or pass a path)")

    d = json.load(open(path))
    print(f"Analyzing {path}")
    runs = d.get("meta", {}).get("runs", [])
    if runs:
        print("Runs:", ", ".join(f"R{r['round']}{'·'+r['mode'] if r.get('mode') else ''}({r['count']})" for r in runs))
    analyze("LIBRARY (everyone)", d.get("recommendations", []))
    for u in d.get("users", []):
        analyze(f"USER · {u.get('label', u.get('id'))}", u.get("recommendations", []))


if __name__ == "__main__":
    main()
