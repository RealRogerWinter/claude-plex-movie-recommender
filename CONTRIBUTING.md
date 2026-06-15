# Contributing

Thanks for your interest! This is a [Claude Code](https://claude.com/claude-code) skill that turns a Plex
library into a recommendation atlas. Bug fixes, new library backends, prompt improvements, and UI polish are
all welcome.

## How the project is laid out
- **`prompts/`** — the heart of the skill. Each pipeline stage is a reusable prompt with a strict JSON
  contract; they carry the quality bar (tie every pick to the library, triangulate ≥2 sources, never
  re-recommend owned titles). Read the relevant prompt before changing a stage.
- **`scripts/`** — deterministic Python (standard library only): scan, diff/track, assemble/build, deploy,
  plus the `pipeline.workflow.js` engine that fans the research out in parallel.
- **`assets/templates/`** — the static site (HTML/CSS/vanilla JS + D3 from a CDN). No build step.
- **`references/`** — the data contract and the configuration / integrations / deploy docs.

## Ground rules
- **Never commit personal data.** No real config (`config.json` is git-ignored), library snapshots, tokens,
  API keys, domains, or usernames. Everything installation-specific belongs in your local
  `~/.config/recommendations/config.json`; the repo stays generic and shareable.
- **No build step, few dependencies.** The site is static and Python is stdlib-only. Don't add a bundler or
  pip dependencies without a strong reason and prior discussion.
- **Keep the data contract stable.** The frontend reads one `data.json` (see
  [`references/data-schema.md`](references/data-schema.md)). If you change it, update the schema, the builder
  (`build_site.py`), and the renderer (`render.js` / `map.js`) together — and keep `render.js`'s ids/classes
  and `RecMap.init` intact.
- **New library backends are welcome** behind `library.source` (Plex is the one implemented today). Emit the
  same snapshot shape so the rest of the pipeline is unchanged.

## Testing your change
- **UI only (no Plex needed):** `python3 scripts/serve.py --dir assets/templates`, then open
  `http://localhost:8000/index.html?data=data.sample.json` to render the bundled sample data.
- **Pipeline / scripts:** run against your own Plex. `python3 scripts/config.py show` prints the merged
  config; after a daring/discovery run, `python3 scripts/analyze_runs.py` compares modes.
- Before committing, skim `git diff` to be sure no personal data slipped in.

## Submitting
1. Open an issue to discuss anything non-trivial first.
2. Fork, branch, keep the PR focused, and describe what changed and why.
3. Match the surrounding code style — small functions, and comments that explain the *why*.

By contributing, you agree your work is licensed under the repository's [MIT License](LICENSE).
