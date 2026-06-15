# Security Policy

## Supported versions
This is an actively developed, single-track project — fixes land on `main`. Please test against the latest
`main` before reporting.

## Reporting a vulnerability
**Please do not open a public issue for security problems.** Use GitHub's private reporting on this
repository: **Security → Report a vulnerability** (Private Vulnerability Reporting). Include reproduction
steps and the impact. This is a small project, so expect a best-effort response.

## What's security-relevant (by design)
This skill handles credentials and can publish data, so a few areas matter:
- **Secrets are read at runtime, never stored or published.** The Plex token and any Tautulli / Seerr / TMDB
  keys are resolved on demand (env var → config file → `docker exec` → `sudo`) and held in memory only.
  Report any path that could write a token/key into `data.json`, the built `site/`, a log, or a committed file.
- **Posters are localized.** `build_site.py` downloads posters and blanks any Plex/LAN URL, so the published
  page never carries a token-bearing URL. Flag any case where a `localhost:32400` / token URL could ship.
- **Publishing is world-readable by design.** The generated site exposes your library + recommendations —
  gate it (HTTP Basic Auth / a tunnel; see [`references/deploy.md`](references/deploy.md)). The bundled
  request proxy (`scripts/request_proxy.py`) holds a Seerr key server-side and must sit behind your auth.
- **Keep personal data out of the repo.** `config.json`, `state/`, `work/`, `site/`, and `posters/` are
  git-ignored; report any path that would leak them into a commit.
