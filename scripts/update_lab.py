"""Run the whole lab pipeline: fetch-github-data -> compute-lab-state -> generate-lab-svg.

Each stage is also runnable on its own; this wrapper keeps one command for local use and tests.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_common import CONFIG_PATH, LOG, ROOT, SNAPSHOT_PATH, STATE_PATH, SVG_PATH, read_json, setup_logging, six_month_start, write_json  # noqa: E402


def load_stage(filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py").replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_stage = load_stage("fetch-github-data.py")
compute_stage = load_stage("compute-lab-state.py")
render_stage = load_stage("generate-lab-svg.py")

fetch_snapshot = fetch_stage.fetch_snapshot
request_json = fetch_stage.request_json
compute_state = compute_stage.compute_state
chart_markup = render_stage.chart_markup
render_svg = render_stage.render_svg

# ROOT, read_json and request_json stay importable for other generators (e.g. harness panels).
__all__ = ["ROOT", "chart_markup", "compute_state", "fetch_snapshot", "read_json", "render_svg", "request_json",
           "six_month_start"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot to use instead of fetching")
    parser.add_argument("--output", type=Path, default=SVG_PATH)
    args = parser.parse_args()
    try:
        config = read_json(CONFIG_PATH)
        now = datetime.now(timezone.utc)
        if args.fixture:
            snapshot = read_json(args.fixture)
        else:
            snapshot = fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""), now)
            write_json(SNAPSHOT_PATH, snapshot)
        state = compute_state(snapshot, config, now)
        if not args.fixture:
            write_json(STATE_PATH, state)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_svg(state), encoding="utf-8")
        LOG.info("Generated %s: %s / %s, %s machines", args.output,
                 state["activity"], state["condition"], len(state["machines"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Lab generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
