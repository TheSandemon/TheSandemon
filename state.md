# Lab system state

- The profile README uses `assets/lab.svg` and LadderStar's published Open Graph image as its linked feature preview.
- The lab is a build facility with no character: a reactor core powers up to five machine bays (one per repo active in the last 14 days) through cables whose flow speed follows activity. A monitor scrolls six months of daily contributions and a build log cycles recent public events.
- Pipeline, each stage runnable on its own:
  1. `scripts/fetch-github-data.py` fetches contributions (GraphQL), public events, recently pushed repos and the latest workflow conclusion, and writes a trimmed `data/snapshot.json`.
  2. `scripts/compute-lab-state.py` turns the snapshot into durable states (activity SLEEPING/TINKERING/BUILDING/OVERCLOCKED, condition STABLE/ENERGIZED/WARNING/CRITICAL, mode RESEARCH/EXPERIMENTING/OPEN-SOURCE/SHIPPING, machines, log lines) in `data/lab-state.json`.
  3. `scripts/generate-lab-svg.py` renders `assets/lab.svg`. Palette follows condition; loop tempo, cable flow and ambient light follow activity.
  `scripts/update_lab.py` runs all three in one go; `--fixture` renders from an offline snapshot without writing `data/`.
- The workflow runs on schedule, manual dispatch, and pushes to `main` that touch scripts, config or the workflow, and commits only changed outputs (`assets/lab.svg`, `assets/harness-*.svg`, `data/`, `README.md`).
- The default Actions token exposes public contribution history. To include private contribution counts in this public SVG, add an optional `LAB_HISTORY_TOKEN` repository secret with `read:user` access. Do not use a broad personal token.
- Customize username, thresholds, display aliases (`focus_aliases`), `ignore_repos` and `machine_slots` (1-5) in `config/lab.json`. Keep every animation indefinitely repeating and the first frame readable.
- Local checks: `python -m unittest discover -s tests` and `python scripts/update_lab.py --fixture tests/fixtures/snapshot.json`.

# Harness panels

- `scripts/update_harness.py` searches the user's public PRs and commits, fetches file lists for the newest (and featured) PRs, and renders `assets/harness-chat.svg`, `assets/harness-terminal.svg` and `assets/harness-flow.svg`. It rewrites only the block between `<!-- harness:start -->` and `<!-- harness:end -->` in `README.md`.
- Panels: chat shows the top task (PR title, plan steps from the PR body's bullets, files, result); terminal scrolls recent commits with per-repo meters; flow shows plan/build/verify/ship for the second task, lighting stages by PR state (draft → build, open → verify, merged → ship).
- `config/profile-visuals.json` controls `repo_aliases`, `ignored_repos`, `ignored_patterns` (regexes on PR titles and commit subjects), `featured` (`"repo#number"` keys pinned first), `summaries` (`"repo#number"` → a string or list of plan steps replacing the PR body), and `panels` (order, `label`, `subtitle`, `hidden`; `id` becomes the file name).
- The workflow gives this step the default Actions token and the search adds `is:public`, so private work never reaches the public SVGs unless `include_private` is set.
- Offline render: `python scripts/update_harness.py --fixture tests/fixtures/harness-snapshot.json` (a snapshot of this repo's real PRs and commits).
