# Lab system state

- The profile README uses `assets/lab.svg` and LadderStar's published Open Graph image as its linked feature preview.
- `scripts/update_lab.py` fetches the prior six calendar months of daily GitHub contributions through GraphQL, derives lab mood and system condition, and renders an SVG with a scrolling history monitor. Public events only supply a current repository label. The scheduled/manual workflow commits changed SVG output.
- The default Actions token exposes public contribution history. To include private contribution counts in this public SVG, add an optional `LAB_HISTORY_TOKEN` repository secret with `read:user` access. Do not use a broad personal token.
- Customize username, contribution thresholds, and repository display aliases in `config/lab.json`. Change scene geometry, palette, or motion in `render_svg()`; keep every animation indefinitely repeating and the first frame readable.
- Local checks: `python -m unittest discover -s tests` and `python scripts/update_lab.py`. A JSON snapshot can be passed with `--fixture` for offline rendering.

# Harness panels

- `scripts/update_harness.py` searches the user's public PRs and commits, fetches file lists for the newest (and featured) PRs, and renders `assets/harness-chat.svg`, `assets/harness-terminal.svg` and `assets/harness-flow.svg`. It rewrites only the block between `<!-- harness:start -->` and `<!-- harness:end -->` in `README.md`.
- Panels: chat shows the top task (PR title, plan steps from the PR body's bullets, files, result); terminal scrolls recent commits with per-repo meters; flow shows plan/build/verify/ship for the second task, lighting stages by PR state (draft → build, open → verify, merged → ship).
- `config/profile-visuals.json` controls `repo_aliases`, `ignored_repos`, `ignored_patterns` (regexes on PR titles and commit subjects), `featured` (`"repo#number"` keys pinned first), `summaries` (`"repo#number"` → a string or list of plan steps replacing the PR body), and `panels` (order, `label`, `subtitle`, `hidden`; `id` becomes the file name).
- The workflow gives this step the default Actions token and the search adds `is:public`, so private work never reaches the public SVGs unless `include_private` is set.
- Offline render: `python scripts/update_harness.py --fixture tests/fixtures/harness-snapshot.json` (a snapshot of this repo's real PRs and commits).
