#!/usr/bin/env python3
"""Tautulli integration — per-user watch-history "basis".

Where the full-library scan (scan_library.py) lists everything *on the server*, this module
asks Tautulli what a *single user* has actually watched, and shapes it like a library snapshot
so the same recommendation pipeline can run for that person.

  * read_key(...)        -> the Tautulli API key, from env / docker exec / sudo. NEVER printed.
  * get_users(base,key)  -> active real users [{user_id, name}] (drops the synthetic user_id 0).
  * user_basis(base,key,user,limit) -> a list shaped like library-latest.json items
      ({id,title,type,year,genres,director,summary,poster,weight}) built from that user's
      get_history: movies counted individually, episodes rolled up to their show, each weighted
      by play_count * completion * recency; the top `limit` are enriched via get_metadata.

The basis is the per-user analogue of state/library-latest.json: scan_library.py writes it to
<workdir>/users/<slug>/state/library-latest.json and the normal pipeline takes it from there.

Pure stdlib. The Tautulli API is `GET <base>/api/v2?apikey=KEY&cmd=<command>&...` returning
{"response": {"result": "success", "data": ...}}.
"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plexlib as P  # noqa: E402

# Tautulli's get_history media_type -> our library "type" (movie | show). Episodes roll up to show.
_TYPE = {"movie": "movie", "episode": "show", "show": "show", "season": "show", "live": "movie"}


def _key_from_ini(text):
    """Parse api_key from [General] of a Tautulli config.ini using configparser."""
    if not text:
        return None
    import configparser
    cp = configparser.ConfigParser()
    try:
        cp.read_string(text)
    except Exception:  # noqa: BLE001 — fall back to a tolerant scan below
        cp = None
    if cp and cp.has_option("General", "api_key"):
        v = cp.get("General", "api_key").strip().strip('"').strip("'")
        if v:
            return v
    # tolerant fallback for slightly non-standard ini (e.g. stray characters)
    import re
    m = re.search(r'(?im)^\s*api_key\s*=\s*"?([0-9a-fA-F]{16,})"?', text)
    return m.group(1) if m else None


def read_key(container="tautulli", config_path="/config/config.ini"):
    """Read the Tautulli API key from the least-privileged source that works. Never print it.

    Order: TAUTULLI_API_KEY env -> `docker exec <container> cat <config_path>` ->
    `sudo -n cat <TAUTULLI_CONFIG host path>`. Tautulli's config.ini is typically only
    readable inside the container, so the docker fallback is what usually succeeds."""
    k = os.environ.get("TAUTULLI_API_KEY")
    if k:
        return k

    cmds = [["docker", "exec", container, "cat", config_path]]
    host = os.environ.get("TAUTULLI_CONFIG")
    if host:
        cmds.append(["sudo", "-n", "cat", host])
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                k = _key_from_ini(r.stdout)
                if k:
                    return k
        except Exception:  # noqa: BLE001
            continue
    print("[tautulli] could not read API key (tried TAUTULLI_API_KEY, docker exec, sudo).", file=sys.stderr)
    return None


def _call(base, key, cmd, timeout=30, **params):
    """One Tautulli API call. Returns the `data` payload (or {} on a non-success result)."""
    q = {"apikey": key, "cmd": cmd, "out_type": "json"}
    q.update({k: v for k, v in params.items() if v is not None})
    url = f"{base.rstrip('/')}/api/v2?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    resp = (payload or {}).get("response", {}) or {}
    if resp.get("result") != "success":
        raise RuntimeError(f"Tautulli {cmd} failed: {resp.get('message') or resp.get('result')}")
    return resp.get("data", {})


def get_users(base, key, timeout=30):
    """Active, real users as [{user_id, name}]. Drops the synthetic Local/user_id 0 and inactive ones."""
    data = _call(base, key, "get_users", timeout=timeout)
    rows = data if isinstance(data, list) else (data.get("data") or [])
    out = []
    for u in rows:
        try:
            uid = int(u.get("user_id"))
        except (TypeError, ValueError):
            continue
        if uid == 0:
            continue
        # Tautulli marks deactivated users with is_active == 0 (older builds omit the field).
        if str(u.get("is_active", 1)) in ("0", "False", "false"):
            continue
        name = u.get("friendly_name") or u.get("username") or u.get("email") or str(uid)
        out.append({"user_id": uid, "name": name})
    return out


def _to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _completion(row):
    """0..1 how much of the item was watched. Prefer percent_complete; else view_offset/duration."""
    pc = row.get("percent_complete")
    if pc not in (None, ""):
        return max(0.0, min(1.0, _to_float(pc) / 100.0))
    dur = _to_float(row.get("duration"))
    off = _to_float(row.get("view_offset"))
    if dur > 0 and off > 0:
        return max(0.0, min(1.0, off / dur))
    # watched flag, else assume a meaningful partial play
    if str(row.get("watched_status", "")) in ("1", "True", "true"):
        return 1.0
    return 0.5


def _recency(row, newest):
    """0..1 recency: a gentle linear ramp over ~2 years back from the newest play in the history."""
    when = _to_float(row.get("date") or row.get("started") or row.get("stopped"))
    if when <= 0 or newest <= 0:
        return 0.5
    span = 2 * 365 * 24 * 3600  # two years, in seconds (Tautulli timestamps are epoch seconds)
    age = max(0.0, newest - when)
    return max(0.15, 1.0 - min(1.0, age / span))


def _history_rows(base, key, user_id, length, timeout):
    data = _call(base, key, "get_history", timeout=timeout, user_id=user_id, length=length,
                 order_column="date", order_dir="desc")
    return data.get("data") or [] if isinstance(data, dict) else []


def user_basis(base, key, user, limit=80, length=10000, timeout=45):
    """Build a per-user library-shaped basis from Tautulli watch history.

    `user` is the username/friendly name; we resolve it to a user_id via get_users. Movies are
    aggregated individually; episodes are rolled up to their parent show (grandparent_title /
    grandparent_rating_key). Each aggregate's weight = sum(play_count * completion * recency)
    across its plays. The top `limit` aggregates are enriched with get_metadata (genres, year,
    summary, thumb, directors). Items are deduped via plexlib.make_key. Returns a list ordered
    by descending weight.
    """
    users = get_users(base, key, timeout=timeout)
    uid = None
    for u in users:
        if u["name"] == user or str(u["user_id"]) == str(user):
            uid = u["user_id"]
            break
    if uid is None:
        # fall back to case-insensitive match before giving up
        for u in users:
            if u["name"].lower() == str(user).lower():
                uid = u["user_id"]
                break
    if uid is None:
        raise RuntimeError(f"Tautulli user not found: {user!r}")

    rows = _history_rows(base, key, uid, length, timeout)
    newest = max([_to_float(r.get("date")) for r in rows] or [0.0])

    # aggregate movies individually, episodes up to their show
    aggs = {}  # agg_key -> aggregate dict
    for r in rows:
        mt = (r.get("media_type") or "").lower()
        typ = _TYPE.get(mt)
        if typ is None:
            continue
        if typ == "show":
            rating_key = r.get("grandparent_rating_key") or r.get("parent_rating_key")
            title = r.get("grandparent_title") or r.get("parent_title") or r.get("title")
        else:
            rating_key = r.get("rating_key")
            title = r.get("title") or r.get("full_title")
        if not title:
            continue
        year = r.get("year") or ""
        agg_key = ("rk", str(rating_key)) if rating_key else ("mk", P.make_key(title, year, typ))
        plays = max(1.0, _to_float(r.get("play_count"), 1.0))
        w = plays * _completion(r) * _recency(r, newest)
        a = aggs.get(agg_key)
        if a is None:
            aggs[agg_key] = {
                "rating_key": rating_key, "title": title, "type": typ,
                "year": str(year) if year else "", "weight": w, "plays": plays,
            }
        else:
            a["weight"] += w
            a["plays"] += plays
            if not a["year"] and year:
                a["year"] = str(year)

    # collapse anything that still collides on the fuzzy (title,year,type) identity
    by_make = {}
    for a in aggs.values():
        mk = P.make_key(a["title"], a["year"], a["type"])
        if mk in by_make:
            keep = by_make[mk]
            keep["weight"] += a["weight"]
            keep["plays"] += a["plays"]
            if not keep["rating_key"] and a["rating_key"]:
                keep["rating_key"] = a["rating_key"]
        else:
            by_make[mk] = a

    ordered = sorted(by_make.values(), key=lambda a: a["weight"], reverse=True)

    out = []
    for i, a in enumerate(ordered):
        rec = {
            "id": "basis-" + (str(a["rating_key"]) if a["rating_key"]
                              else P.norm_title(a["title"]).replace(" ", "-")[:40] or str(i)),
            "title": a["title"],
            "type": a["type"],
            "year": a["year"],
            "genres": [],
            "director": None,
            "summary": "",
            "poster": "",
            "weight": round(a["weight"], 4),
        }
        # enrich only the top `limit` by weight — keep API calls bounded
        if i < (limit or 0) and a["rating_key"]:
            try:
                md = _call(base, key, "get_metadata", timeout=timeout, rating_key=a["rating_key"])
                if isinstance(md, dict) and md:
                    rec["genres"] = [g for g in (md.get("genres") or []) if g]
                    rec["year"] = str(md.get("year") or rec["year"] or "")
                    rec["summary"] = md.get("summary", "") or ""
                    rec["director"] = (md.get("directors") or [None])[0]
                    rec["poster"] = md.get("thumb", "") or ""  # token-free Plex thumb path
            except Exception as e:  # noqa: BLE001 — enrichment is best-effort
                print(f"[tautulli] metadata lookup failed for {a['title']}: {e}", file=sys.stderr)
        out.append(rec)

    return out[: limit] if limit else out
