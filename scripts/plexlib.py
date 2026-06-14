#!/usr/bin/env python3
"""Shared helpers for the /recommendations skill: Plex access, key normalization,
HTTP, and small filesystem utilities. Pure stdlib so it runs anywhere python3 does."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_BASE = os.environ.get("PLEX_BASE_URL", "http://localhost:32400")
DEFAULT_PREFS = os.environ.get(
    "PLEX_PREFS",
    os.path.expanduser("~/Library/Application Support/Plex Media Server/Preferences.xml"),
)
DEFAULT_WORKDIR = os.environ.get("REC_WORKDIR", os.path.expanduser("~/recommendations"))

_ARTICLES = ("the ", "a ", "an ")


def _token_from_text(text):
    if not text:
        return None
    m = re.search(r'PlexOnlineToken="([^"]+)"', text)
    return m.group(1) if m else None


def read_plex_token(prefs_path=DEFAULT_PREFS):
    """Read PlexOnlineToken, trying the least-privileged source that works. Never print it.

    Order: PLEX_TOKEN env -> direct file read -> `docker exec <plex> cat` ->
    `sudo -n cat`. The Preferences.xml is typically mode 600 owned by the container
    user, so on this host the docker/sudo fallbacks are what actually succeed."""
    import subprocess
    tok = os.environ.get("PLEX_TOKEN")
    if tok:
        return tok

    # 1. direct read (works only if perms allow)
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            tok = _token_from_text(f.read())
        if tok:
            return tok
    except Exception:  # noqa: BLE001
        pass

    # 2. via the Plex container (it can always read its own config)
    container = os.environ.get("PLEX_CONTAINER", "plex")
    cprefs = os.environ.get(
        "PLEX_CONTAINER_PREFS",
        "/config/Library/Application Support/Plex Media Server/Preferences.xml",
    )
    for cmd in (["docker", "exec", container, "cat", cprefs],
                ["sudo", "-n", "cat", prefs_path]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                tok = _token_from_text(r.stdout)
                if tok:
                    return tok
        except Exception:  # noqa: BLE001
            continue
    print(f"[plexlib] could not obtain Plex token (tried env, {prefs_path}, docker, sudo).", file=sys.stderr)
    return None


def norm_title(t):
    t = (t or "").lower().strip()
    t = re.sub(r"[‘’']", "", t)          # smart/plain apostrophes
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    for a in _ARTICLES:
        if t.startswith(a):
            t = t[len(a):]
            break
    return re.sub(r"\s+", " ", t).strip()


def make_key(title, year, typ):
    """Stable, fuzzy identity for a title used for diffing and owned/recommended checks."""
    return f"{typ}|{norm_title(title)}|{str(year or '').strip()}"


def http_get_json(url, token=None, timeout=30):
    if token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}X-Plex-Token={urllib.parse.quote(token)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def download(url, dest, token=None, timeout=60):
    """Download url -> dest. Returns True on success. Plex thumb paths get the token here
    (so the saved file is token-free and the data file never carries the secret)."""
    if token and "X-Plex-Token=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}X-Plex-Token={urllib.parse.quote(token)}"
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "recommendations-skill/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            f.write(r.read())
        return os.path.getsize(dest) > 0
    except Exception as e:  # noqa: BLE001
        print(f"[plexlib] poster download failed ({url.split('?')[0]}): {e}", file=sys.stderr)
        if os.path.exists(dest):
            os.remove(dest)
        return False


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa: BLE001
        print(f"[plexlib] could not read {path}: {e}", file=sys.stderr)
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def today():
    """ISO date. (Python scripts may use datetime; only the Workflow JS engine forbids it.)"""
    import datetime
    return datetime.date.today().isoformat()


def now_stamp():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
