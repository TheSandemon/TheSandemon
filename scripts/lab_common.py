"""Shared helpers for the lab pipeline: fetch-github-data -> compute-lab-state -> generate-lab-svg."""

from __future__ import annotations

import calendar
from datetime import date
import json
import logging
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "lab.json"
SNAPSHOT_PATH = ROOT / "data" / "snapshot.json"
STATE_PATH = ROOT / "data" / "lab-state.json"
SVG_PATH = ROOT / "assets" / "lab.svg"
LOG = logging.getLogger("sandemon.lab")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top-level value must be an object")
        return value
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Cannot read JSON from {path}: {exc}") from exc


def write_json(path: Path, value: dict) -> None:
    """Write sorted, indented JSON so committed data diffs stay readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def six_month_start(today: date) -> date:
    month_index = today.year * 12 + today.month - 1 - 6
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
