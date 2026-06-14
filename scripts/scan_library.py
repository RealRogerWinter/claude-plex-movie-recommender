#!/usr/bin/env python3
"""Stage 0 — scan the library into a run snapshot.

Two sources, same output shape:

  * full library (default, `library.source: plex`) — enumerates every movie and show across all
    Plex library sections, dedupes by a normalized (type, title, year) key (the tiered storage +
    the separate USB library can list the same film twice), and writes:

        <workdir>/state/library-latest.json   # full records, fed into the pipeline
        <workdir>/state/library-latest.txt    # human-readable "Title (Year) [type]" list

  * per-user basis (`--user NAME`, source `tautulli-user`) — asks Tautulli what that one user has
    actually watched (tautulli.user_basis) and writes the same two files under that user's subdir:

        <workdir>/users/<slug>/state/library-latest.json
        <workdir>/users/<slug>/state/library-latest.txt

The snapshot is what the next run diffs against to drive the feedback loop.
Poster values are stored as token-free Plex paths; build_site.py downloads them later.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plexlib as P  # noqa: E402
import config as C  # noqa: E402
import tautulli as T  # noqa: E402


def slug(name):
    """Lowercased alphanumeric form of a username — the per-user subdir name under users/."""
    s = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    return s or "user"


def items_of(mc):
    # Plex JSON puts items under Metadata (modern) or Video/Directory (older builds).
    return mc.get("Metadata") or (mc.get("Video", []) + mc.get("Directory", []))


def tags(obj, key):
    return [t.get("tag") for t in obj.get(key, []) if t.get("tag")]


def scan(base, token, timeout):
    sections = P.http_get_json(f"{base}/library/sections", token, timeout)
    dirs = sections.get("MediaContainer", {}).get("Directory", [])
    out, seen = [], {}
    for d in dirs:
        stype = d.get("type")
        if stype not in ("movie", "show"):
            continue
        kind = "movie" if stype == "movie" else "show"
        key = d.get("key")
        data = P.http_get_json(f"{base}/library/sections/{key}/all", token, timeout)
        for it in items_of(data.get("MediaContainer", {})):
            title, year = it.get("title"), it.get("year")
            if not title:
                continue
            rec = {
                "id": "lib-" + str(it.get("ratingKey")),
                "ratingKey": it.get("ratingKey"),
                "title": title,
                "type": kind,
                "year": str(year) if year else "",
                "genres": tags(it, "Genre"),
                "director": (tags(it, "Director") or [None])[0],
                "summary": it.get("summary", ""),
                "poster": it.get("thumb", ""),   # token-free path, e.g. /library/metadata/123/thumb/...
                "section": d.get("title"),
            }
            k = P.make_key(title, rec["year"], kind)
            # keep the richer record if we see a title twice across sections/tiers
            if k in seen:
                prev = out[seen[k]]
                if len(rec["genres"]) > len(prev["genres"]) or (rec["poster"] and not prev["poster"]):
                    out[seen[k]] = rec
                continue
            seen[k] = len(out)
            out.append(rec)
    out.sort(key=lambda r: (r["type"], P.norm_title(r["title"])))
    return out


def write_snapshot(state, lib):
    """Write the library-latest.json + .txt snapshot pair into `state`. Shared by both sources."""
    P.write_json(os.path.join(state, "library-latest.json"), lib)
    with open(os.path.join(state, "library-latest.txt"), "w", encoding="utf-8") as f:
        for r in lib:
            yr = f" ({r['year']})" if r["year"] else ""
            f.write(f"{r['title']}{yr} [{r['type']}]\n")


def scan_user(cfg, user, limit, timeout):
    """Build one user's Tautulli watch-history basis (shaped like the full-library snapshot)."""
    tcfg = C.get(cfg, "library.tautulli", {}) or {}
    base = tcfg.get("base_url", "http://localhost:8181")
    key = T.read_key(tcfg.get("container", "tautulli"), tcfg.get("config_path", "/config/config.ini"))
    if not key:
        print("ERROR: no Tautulli API key (set TAUTULLI_API_KEY, or ensure docker/sudo access).", file=sys.stderr)
        sys.exit(2)
    return T.user_basis(base, key, user, limit=limit or 80, timeout=timeout)


def main():
    ap = argparse.ArgumentParser(description="Scan the library (or one user's watch history) into a run snapshot.")
    ap.add_argument("--config", help="path to a config.json (else auto-resolved)")
    ap.add_argument("--workdir")
    ap.add_argument("--source", help="override library.source (e.g. plex, tautulli-user)")
    ap.add_argument("--user", help="build a per-user basis from Tautulli watch history for this username")
    ap.add_argument("--base-url")
    ap.add_argument("--prefs")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--limit", type=int, default=0, help="cap items (for quick demos); 0 = all")
    args = ap.parse_args()

    cfg = C.load(args.config)
    workdir = args.workdir or cfg["workdir"]

    # Resolve the source: an explicit --user implies the per-user (tautulli-user) source.
    source = args.source or ("tautulli-user" if args.user else C.get(cfg, "library.source", "plex"))

    # ---- per-user basis (Tautulli watch history) ---------------------------------
    if args.user or source == "tautulli-user":
        if not args.user:
            print("ERROR: source 'tautulli-user' requires --user NAME.", file=sys.stderr)
            sys.exit(2)
        try:
            lib = scan_user(cfg, args.user, args.limit, args.timeout)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: Tautulli basis for {args.user!r} failed: {e}", file=sys.stderr)
            sys.exit(1)
        state = os.path.join(workdir, "users", slug(args.user), "state")
        write_snapshot(state, lib)
        movies = sum(1 for r in lib if r["type"] == "movie")
        shows = len(lib) - movies
        print(f"Built basis for {args.user!r}: {len(lib)} watched titles ({movies} movies, {shows} shows).")
        print(f"Snapshot: {os.path.join(state, 'library-latest.json')}")
        return

    # ---- full library scan (default) ---------------------------------------------
    base = args.base_url or C.get(cfg, "library.plex.base_url", P.DEFAULT_BASE)
    prefs = args.prefs or C.get(cfg, "library.plex.prefs_path", P.DEFAULT_PREFS)

    token = P.read_plex_token(prefs)
    if not token:
        print("ERROR: no Plex token (set PLEX_TOKEN, --prefs, or config library.plex.prefs_path).", file=sys.stderr)
        sys.exit(2)

    try:
        lib = scan(base, token, args.timeout)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: Plex scan failed: {e}", file=sys.stderr)
        sys.exit(1)

    if args.limit:
        # keep a representative spread (every Nth) rather than just the alphabetic head
        step = max(1, len(lib) // args.limit)
        lib = lib[::step][: args.limit]

    state = os.path.join(workdir, "state")
    write_snapshot(state, lib)

    movies = sum(1 for r in lib if r["type"] == "movie")
    shows = len(lib) - movies
    print(f"Scanned {len(lib)} unique titles: {movies} movies, {shows} shows.")
    print(f"Snapshot: {os.path.join(state, 'library-latest.json')}")


if __name__ == "__main__":
    main()
