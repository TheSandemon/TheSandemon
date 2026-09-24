# Lab system state

- The profile README uses `assets/lab.svg` and LadderStar's published Open Graph image as its linked feature preview.
- The lab is a build facility with no character: a reactor core powers up to five machine bays (one per repo active in the last 14 days) through cables whose flow speed follows activity. A monitor scrolls six months of daily contributions and a build log cycles recent public events.
- Pipeline, each stage runnable on its own:
  1. `scripts/fetch-github-data.py` fetches contributions (GraphQL), public events, recently pushed repos and the latest workflow conclusion, and writes a trimmed `data/snapshot.json`.
  2. `scripts/compute-lab-state.py` turns the snapshot into durable states (activity SLEEPING/TINKERING/BUILDING/OVERCLOCKED, condition STABLE/ENERGIZED/WARNING/CRITICAL, mode RESEARCH/EXPERIMENTING/OPEN-SOURCE/SHIPPING, machines, log lines) in `data/lab-state.json`.
  3. `scripts/generate-lab-svg.py` renders `assets/lab.svg`. Palette follows condition; loop tempo, cable flow and ambient light follow activity.
  `scripts/update_lab.py` runs all three in one go; `--fixture` renders from an offline snapshot without writing `data/`.
- The workflow runs on schedule, manual dispatch, and pushes to `main` that touch scripts, config or the workflow, and commits only changed outputs (`assets/lab.svg`, `data/`).
- The default Actions token exposes public contribution history. To include private contribution counts in this public SVG, add an optional `LAB_HISTORY_TOKEN` repository secret with `read:user` access. Do not use a broad personal token.
- Customize username, thresholds, display aliases (`focus_aliases`), `ignore_repos` and `machine_slots` (1-5) in `config/lab.json`. Keep every animation indefinitely repeating and the first frame readable.
- Local checks: `python -m unittest discover -s tests` and `python scripts/update_lab.py --fixture tests/fixtures/snapshot.json`.
