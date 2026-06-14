# Deploying the report

The skill builds a self-contained static site in `<workdir>/site/` (`index.html`, `map.html`,
`data.json`, downloaded `posters/`). Publish it however you like. All deploy settings come from your
config (`deploy.*`), so once configured, publishing is a single command.

> **Publishing is public and outward-facing.** The library list and recommendations become
> world-readable and may be indexed by search engines. Treat the first publish — and any DNS change —
> as a confirm-first action. Keep personal data out of any repo you intend to open-source: the site
> output (`site/` / `docs/`) is your *personal* data; the **skill source is the generic, shareable part**.

---

## Path A — GitHub Pages (recommended)

`gh` must be authenticated. `scripts/deploy.sh` reads `deploy.repo`, `deploy.domain`,
`deploy.visibility`, `deploy.branch`, `deploy.git_name`, `deploy.git_email` from config; CLI flags override.

1. **Build:**
   ```bash
   python3 scripts/build_site.py --workdir ~/recommendations --append ~/recommendations/work/recommendations.json
   ```
2. **Publish:**
   ```bash
   scripts/deploy.sh                 # or: scripts/deploy.sh --repo OWNER/REPO --domain sub.example.org --public
   ```
   The script creates the repo if missing (**private** unless `deploy.visibility` is `public` / `--public`),
   copies `site/` → `docs/`, writes `docs/CNAME` when a domain is set, commits, and pushes.
3. **Enable Pages** (once): repo → Settings → Pages → Source = your branch / `/docs`. Or:
   ```bash
   gh api -X POST repos/OWNER/REPO/pages -f "source[branch]=main" -f "source[path]=/docs"
   ```
4. **Custom domain** (optional): set `deploy.domain`. A **subdomain** is the easy path — add ONE DNS
   record at your DNS provider: `CNAME  <sub> → <owner>.github.io` (set it DNS-only / unproxied until
   the certificate issues, then enable **Enforce HTTPS** in Pages settings).

Re-publishing later is just steps 1–2 (idempotent; `deploy.sh` syncs `site/` → `docs/`).

> Keeping the skill open-sourceable: publish the **site** from a repo that holds only `docs/` (your
> data), and keep the **skill** in a separate repo (or the skill at the repo root with the generated
> `docs/` git-ignored). Don't commit your personal `config.json` — it's resolved from
> `~/.config/recommendations/config.json`, outside the skill.

---

## Path B — Self-host the static files

`site/` is plain static files — serve it with any web server, reverse proxy, or tunnel.

1. Build straight into a served directory:
   ```bash
   python3 scripts/build_site.py --workdir ~/recommendations \
       --append ~/recommendations/work/recommendations.json --out /srv/www/recommendations
   ```
2. Point your web server (nginx/caddy/etc.), reverse proxy, or tunnel at that directory. If you run it
   as a container, keep it as its own isolated project — don't fold it into unrelated stacks.

---

## Gate it behind a login (optional)

For a private deploy, add HTTP Basic Auth at the static server — one shared credential, no extra service:

```bash
# create the credential (apr1 hash; works with nginx)
printf '%s:%s\n' "youruser" "$(openssl passwd -apr1 'yourpassword')" > .htpasswd
```
```nginx
# in the server block
add_header Cache-Control "no-store" always;   # behind a CDN: stops cached copies serving without the login
location / {
    auth_basic "Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    try_files $uri $uri/ =404;
}
```
Keep any HTTPS-redirect `if`/`return` at the *server* level so it runs before auth (http visitors get
redirected, not prompted). Mount `.htpasswd` into the container read-only.

---

## Live requests (optional Seerr proxy)

The cards POST to a same-origin **`/api/request`** (create + auto-approve in Seerr) and **`/api/status`**
(live availability, so a reload reflects what's been requested/added). Run `scripts/request_proxy.py` as a
tiny sidecar that holds the Seerr API key (`SEERR_API_KEY`, `SEERR_BASE` env) and reverse-proxy `/api/` to
it from your web server, **behind the same auth gate**. Without the proxy, the cards gracefully fall back
to opening the Seerr title page (the `seerr.url` deep-link).

---

## Notes
- **git identity:** commits use `deploy.git_name` / `deploy.git_email` set repo-locally, so your global
  git config is untouched.
- **Self-contained output:** `build_site.py` downloads every poster locally, so the published site never
  references the Plex host and never leaks the Plex token.
- **D3** loads from a CDN by default; pass `--vendor` to `build_site.py` to download it into `site/vendor/`
  for a fully offline-capable site.
