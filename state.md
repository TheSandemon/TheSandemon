# Lab system state

- The profile README uses `assets/lab.svg` and the linked `assets/ladderstar.svg` feature card.
- `scripts/update_lab.py` fetches public user events, derives a four-level activity state and system condition, and renders a self-contained SVG with indefinite idle loops. The scheduled/manual workflow commits changed SVG output.
- Customize username, activity thresholds, and repository display aliases in `config/lab.json`. Change scene geometry, palette, or motion in `render_svg()`; keep every animation indefinitely repeating and the first frame readable.
- Local checks: `python -m unittest discover -s tests` and `python scripts/update_lab.py`. A JSON snapshot can be passed with `--fixture` for offline rendering.
