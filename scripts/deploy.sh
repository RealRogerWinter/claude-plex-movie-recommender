#!/usr/bin/env bash
# Deploy the built site to GitHub Pages (serves at the custom domain once DNS is set).
# See references/deploy.md for the one-time Pages + Cloudflare DNS steps.
#
#   scripts/deploy.sh --repo OWNER/REPO --domain recommendations.example.org [--public]
#   (repo, domain, visibility, branch default from config deploy.*; CLI flags override)
#
# Publishing is public + outward-facing — only run when you intend to publish.
set -euo pipefail

# defaults come from the resolved config (deploy.*); CLI flags below override them.
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cfg() { python3 "$SKILL_DIR/scripts/config.py" get "$1" 2>/dev/null; }
REPO="$(cfg deploy.repo)"; DOMAIN="$(cfg deploy.domain)"
VIS="$(cfg deploy.visibility)"; BRANCH="$(cfg deploy.branch)"
GIT_NAME="$(cfg deploy.git_name)"; GIT_EMAIL="$(cfg deploy.git_email)"
WORKDIR="$(cfg workdir)"; SITE="${WORKDIR:-$HOME/recommendations}/site"
: "${VIS:=private}"; : "${BRANCH:=main}"
: "${GIT_NAME:=recommendations-bot}"; : "${GIT_EMAIL:=recommendations@users.noreply.github.com}"
MSG="Publish recommendations report"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2;;
    --domain) DOMAIN="$2"; shift 2;;
    --site) SITE="$2"; shift 2;;
    --public) VIS="public"; shift;;
    --branch) BRANCH="$2"; shift 2;;
    --name) GIT_NAME="$2"; shift 2;;
    --email) GIT_EMAIL="$2"; shift 2;;
    --message) MSG="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

[[ -n "$REPO" ]] || { echo "ERROR: --repo owner/name required" >&2; exit 2; }
[[ -d "$SITE" && -f "$SITE/index.html" ]] || { echo "ERROR: no built site at $SITE (run build_site.py)" >&2; exit 2; }
command -v gh >/dev/null || { echo "ERROR: gh not found" >&2; exit 2; }

echo "==> repo: $REPO   site: $SITE   domain: ${DOMAIN:-<none>}   visibility: $VIS"

if ! gh repo view "$REPO" >/dev/null 2>&1; then
  echo "==> creating $VIS repo $REPO"
  gh repo create "$REPO" "--$VIS" --description "Bespoke film & TV recommendations for my library" >/dev/null
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
echo "==> cloning into $TMP"
gh repo clone "$REPO" "$TMP" -- -q 2>/dev/null || git clone "$(gh repo view "$REPO" --json sshUrl -q .sshUrl)" "$TMP"

mkdir -p "$TMP/docs"
rsync -a --delete --exclude '.git' "$SITE"/ "$TMP/docs/"
touch "$TMP/docs/.nojekyll"
[[ -n "$DOMAIN" ]] && echo "$DOMAIN" > "$TMP/docs/CNAME"

if [[ ! -f "$TMP/README.md" ]]; then
  cat > "$TMP/README.md" <<EOF
# ${REPO##*/}

Bespoke film & TV recommendations generated from my own media library by the
\`/recommendations\` Claude Code skill. The site lives in \`docs/\` and is served via
GitHub Pages${DOMAIN:+ at https://$DOMAIN}.

Recommendations accumulate over time: each run diffs the library against the last,
learns from what was added, and appends a new round.
EOF
fi

cd "$TMP"
git config user.name "$GIT_NAME"
git config user.email "$GIT_EMAIL"
git add -A
if git diff --cached --quiet; then
  echo "==> nothing changed; skipping commit"
else
  git commit -q -m "$MSG" -m "" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
  git branch -M "$BRANCH"
  git push -u origin "$BRANCH" -q
  echo "==> pushed to $REPO@$BRANCH"
fi

# best-effort: turn on Pages from main /docs (ignore error if already enabled)
gh api -X POST "repos/$REPO/pages" -f "source[branch]=$BRANCH" -f "source[path]=/docs" >/dev/null 2>&1 \
  && echo "==> enabled GitHub Pages (main /docs)" || echo "==> Pages may already be enabled (set it under Settings > Pages if not)"

echo
echo "Done. Next (one-time):"
echo "  • Settings > Pages: confirm source = $BRANCH /docs${DOMAIN:+, custom domain = $DOMAIN, Enforce HTTPS}"
[[ -n "$DOMAIN" ]] && echo "  • Cloudflare DNS: CNAME $DOMAIN -> ${REPO%%/*}.github.io (DNS-only until the cert issues) — see references/deploy.md"
