# Lab system state

- The profile README uses `assets/lab.svg` and LadderStar's published Open Graph image as its linked feature preview.
- `scripts/update_lab.py` fetches the prior six calendar months of daily GitHub contributions through GraphQL, derives lab mood and system condition, and renders an SVG with a scrolling history monitor. Public events only supply a current repository label. The scheduled/manual workflow commits changed SVG output.
- The default Actions token exposes public contribution history. To include private contribution counts in this public SVG, add an optional `LAB_HISTORY_TOKEN` repository secret with `read:user` access. Do not use a broad personal token.
- Customize username, contribution thresholds, and repository display aliases in `config/lab.json`. Change scene geometry, palette, or motion in `render_svg()`; keep every animation indefinitely repeating and the first frame readable.
- Local checks: `python -m unittest discover -s tests` and `python scripts/update_lab.py`. A JSON snapshot can be passed with `--fixture` for offline rendering.
