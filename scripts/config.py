#!/usr/bin/env python3
"""Config for the /recommendations skill.

The skill itself is generic. Everything installation-specific — which Plex to read, what to
call the site, where to publish — lives in a config file so the skill can be open-sourced as-is.

Resolution order (first found wins, then deep-merged over built-in defaults; env vars win last):
  1. --config <path> / REC_CONFIG
  2. ~/.config/recommendations/config.json     (recommended home for personal settings)
  3. <skill>/config.json                        (local, gitignored)
  4. built-in defaults (see DEFAULTS) + <skill>/config.example.json is the documented template

Usage in scripts:   import config; cfg = config.load(args.config)
Usage from bash:    python3 scripts/config.py get deploy.repo
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plexlib as P  # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "library": {"source": "plex",
                "plex": {"base_url": P.DEFAULT_BASE, "prefs_path": P.DEFAULT_PREFS, "container": "plex"},
                "tautulli": {"base_url": "http://localhost:8181", "container": "tautulli",
                             "config_path": "/config/config.ini", "users": "all"}},
    "personal_recommendations": False,
    "workdir": "~/recommendations",
    "site": {"title": "My Recommendation Atlas", "tagline": "Your library, extended."},
    "deploy": {"provider": "github-pages", "repo": "", "domain": "", "branch": "main",
               "visibility": "private", "git_name": "", "git_email": ""},
    "services": {"seerr": {"enabled": False, "base_url": "http://localhost:5055", "public_url": "",
                           "container": "seerr", "settings_path": "/app/config/settings.json"}},
    "research": {"tmdb_api_key": ""},
    "bounds": {"sampleForTaste": 80, "classifyBatch": 20, "maxClusters": 6, "perCluster": 8},
    "modes": {"daring": False, "discovery": False},
}


def _deep_merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def config_path(explicit=None):
    for p in (explicit, os.environ.get("REC_CONFIG"),
              "~/.config/recommendations/config.json",
              os.path.join(SKILL_DIR, "config.json")):
        if p and os.path.exists(os.path.expanduser(p)):
            return os.path.expanduser(p)
    return None


def load(explicit=None):
    cfg = json.loads(json.dumps(DEFAULTS))
    path = config_path(explicit)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _deep_merge(cfg, json.load(f))
        except Exception as e:  # noqa: BLE001
            print(f"[config] could not read {path}: {e}", file=sys.stderr)

    plex = cfg["library"]["plex"]
    if os.environ.get("REC_WORKDIR"): cfg["workdir"] = os.environ["REC_WORKDIR"]
    if os.environ.get("PLEX_BASE_URL"): plex["base_url"] = os.environ["PLEX_BASE_URL"]
    if os.environ.get("PLEX_PREFS"): plex["prefs_path"] = os.environ["PLEX_PREFS"]
    if os.environ.get("PLEX_CONTAINER"): plex["container"] = os.environ["PLEX_CONTAINER"]
    if os.environ.get("TMDB_API_KEY"): cfg["research"]["tmdb_api_key"] = os.environ["TMDB_API_KEY"]

    # make the container discoverable to plexlib's token fallback without threading it everywhere
    os.environ.setdefault("PLEX_CONTAINER", plex.get("container", "plex"))
    cfg["workdir"] = os.path.expanduser(cfg["workdir"])
    cfg["_path"] = path
    return cfg


def get(cfg, dotted, default=""):
    cur = cfg
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


if __name__ == "__main__":
    cfg = load(os.environ.get("REC_CONFIG"))
    if len(sys.argv) >= 3 and sys.argv[1] == "get":
        v = get(cfg, sys.argv[2], "")
        print(v if not isinstance(v, (dict, list)) else json.dumps(v))
    elif len(sys.argv) >= 2 and sys.argv[1] == "show":
        out = {k: v for k, v in cfg.items() if k != "_path"}
        print(json.dumps(out, indent=2))
    elif len(sys.argv) >= 2 and sys.argv[1] == "path":
        print(cfg.get("_path") or "(none — using defaults)")
    else:
        print("usage: config.py [get <dotted.key> | show | path]", file=sys.stderr)
        sys.exit(2)
