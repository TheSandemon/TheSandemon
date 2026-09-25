"""Run the stats pipeline: fetch-github-data -> compute-lab-state.

Both stages also run on their own. The agent chat reads their outputs (data/snapshot.json and
data/lab-state.json) and imports ROOT, read_json and request_json from here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_common import CONFIG_PATH, LOG, ROOT, SNAPSHOT_PATH, STATE_PATH, read_json, setup_logging, six_month_start, write_json  # noqa: E402


def load_stage(filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py").replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_stage = load_stage("fetch-github-data.py")
compute_stage = load_stage("compute-lab-state.py")

fetch_snapshot = fetch_stage.fetch_snapshot
request_json = fetch_stage.request_json
compute_state = compute_stage.compute_state

# ROOT, read_json and request_json stay importable for the agent chat generator.
__all__ = ["ROOT", "compute_state", "fetch_snapshot", "read_json", "request_json", "six_month_start"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot to compute from, without writing data/")
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
        LOG.info("Computed stats: %s contributions in six months, %s active days",
                 state["total_6mo"], state["active_days"])
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Stats pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
