#!/usr/bin/env python3
"""Seerr (Overseerr-compatible) integration.

For each recommendation (which carries a tmdbId), ask Seerr — via its real API — whether the title
is already in the library, and attach a deep-link to the Seerr title page where the owner can request
it. Requesting reuses **Seerr's own auth** (the user logs into Seerr), so no request proxy or write key
is needed here; we only do read-only availability lookups at build time.

The API key is read at runtime from the Seerr container config and is **never** written into the
published site — only a status label and the public request URL end up in data.json.
"""
import json
import os
import subprocess
import sys
import urllib.request

STATUS = {1: "unknown", 2: "pending", 3: "processing", 4: "partial", 5: "available"}


def read_key(container="seerr", settings_path="/app/config/settings.json"):
    k = os.environ.get("SEERR_API_KEY")
    if k:
        return k
    cmds = [["docker", "exec", container, "cat", settings_path]]
    host = os.environ.get("SEERR_SETTINGS")
    if host:
        cmds.append(["sudo", "-n", "cat", host])
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                k = (json.loads(r.stdout).get("main", {}) or {}).get("apiKey")
                if k:
                    return k
        except Exception:  # noqa: BLE001
            continue
    print("[seerr] could not read API key (tried SEERR_API_KEY, docker exec, sudo).", file=sys.stderr)
    return None


def _status(base, key, kind, tmdb, timeout=15):
    url = f"{base.rstrip('/')}/api/v1/{kind}/{tmdb}"
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return (d.get("mediaInfo") or {}).get("status")


def annotate(data, base_url, public_url, key, timeout=15):
    """Attach rec['seerr'] = {statusCode, status, url} to every recommendation. Returns (#available, #checked)."""
    pub = (public_url or "").rstrip("/")
    avail = checked = 0
    for rec in data.get("recommendations", []):
        tmdb = rec.get("tmdbId")
        rid = rec.get("id", "")
        if not tmdb and rid.startswith("rec-tmdb-"):
            tmdb = rid[len("rec-tmdb-"):]
        kind = "tv" if rec.get("type") == "show" else "movie"
        info = {"statusCode": 0, "status": "none", "url": (f"{pub}/{kind}/{tmdb}" if (pub and tmdb) else pub)}
        if key and tmdb and str(tmdb).isdigit():
            try:
                code = _status(base_url, key, kind, tmdb, timeout)
                checked += 1
                if code:
                    info["statusCode"] = code
                    info["status"] = STATUS.get(code, "unknown")
                    if code >= 4:
                        avail += 1
            except Exception as e:  # noqa: BLE001
                print(f"[seerr] lookup failed for {kind}/{tmdb}: {e}", file=sys.stderr)
        rec["seerr"] = info
    return avail, checked
