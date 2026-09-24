"""Fetch six months of contributions, recent public events, repositories and workflow status.

Writes a compact, stable snapshot to data/snapshot.json for compute-lab-state.py.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from lab_common import CONFIG_PATH, LOG, SNAPSHOT_PATH, read_json, setup_logging, six_month_start, write_json


GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def request_json(url: str, token: str, payload: dict | None = None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "sandemon-profile-lab",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=25) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def trim_event(event: dict) -> dict | None:
    """Keep only the fields the lab reads, so the committed snapshot stays small."""
    try:
        payload = event.get("payload") or {}
        trimmed = {
            "type": str(event["type"]),
            "created_at": str(event["created_at"]),
            "repo": str(event["repo"]["name"]),
        }
    except (KeyError, TypeError, AttributeError):
        return None
    if isinstance(payload, dict):
        if payload.get("action"):
            trimmed["action"] = str(payload["action"])
        if trimmed["type"] == "PushEvent":
            size = payload.get("size", len(payload.get("commits") or []))
            trimmed["size"] = int(size) if isinstance(size, int) else 1
        if trimmed["type"] == "PullRequestEvent" and isinstance(payload.get("pull_request"), dict):
            trimmed["merged"] = bool(payload["pull_request"].get("merged"))
    return trimmed


def trim_repo(repo: dict) -> dict | None:
    try:
        return {
            "name": str(repo["name"]),
            "pushed_at": repo.get("pushed_at"),
            "language": repo.get("language"),
            "fork": bool(repo.get("fork")),
            "archived": bool(repo.get("archived")),
        }
    except (KeyError, TypeError):
        return None


def fetch_snapshot(config: dict, token: str, now: datetime) -> dict:
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to fetch six-month contribution history")
    today = now.date()
    start = six_month_start(today)
    answer = request_json(
        GRAPHQL_URL,
        token,
        {
            "query": GRAPHQL_QUERY,
            "variables": {
                "login": config["username"],
                "from": f"{start.isoformat()}T00:00:00Z",
                "to": f"{today.isoformat()}T23:59:59Z",
            },
        },
    )
    if not isinstance(answer, dict) or answer.get("errors"):
        raise RuntimeError(f"GitHub contribution query failed: {answer.get('errors') if isinstance(answer, dict) else answer}")
    try:
        weeks = answer["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        contributions = [
            {"date": day["date"], "count": day["contributionCount"]}
            for week in weeks
            for day in week["contributionDays"]
        ]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("GitHub contribution response lacked the daily calendar") from exc
    if not contributions:
        raise RuntimeError("GitHub contribution calendar was empty")

    user = quote(config["username"], safe="")
    repo = quote(config["profile_repo"], safe="")
    events, repos, workflow = [], [], "unknown"
    try:
        recent = request_json(f"https://api.github.com/users/{user}/events/public?per_page=100", token)
        if isinstance(recent, list):
            events = [item for item in map(trim_event, recent) if item]
    except RuntimeError as exc:
        LOG.warning("Recent events unavailable: %s", exc)
    try:
        listed = request_json(f"https://api.github.com/users/{user}/repos?sort=pushed&per_page=20", token)
        if isinstance(listed, list):
            repos = [item for item in map(trim_repo, listed) if item]
    except RuntimeError as exc:
        LOG.warning("Repository list unavailable: %s", exc)
    try:
        runs = request_json(
            f"https://api.github.com/repos/{user}/{repo}/actions/runs?status=completed&per_page=1", token
        )
        if isinstance(runs, dict) and runs.get("workflow_runs"):
            workflow = str(runs["workflow_runs"][0].get("conclusion") or "unknown")
    except RuntimeError as exc:
        LOG.warning("Workflow status unavailable: %s", exc)
    return {
        "username": config["username"],
        "contributions": contributions,
        "events": events,
        "repos": repos,
        "workflow": workflow,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()
    try:
        config = read_json(CONFIG_PATH)
        snapshot = fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""), datetime.now(timezone.utc))
        write_json(args.output, snapshot)
        LOG.info("Wrote %s: %s days, %s events, %s repos", args.output,
                 len(snapshot["contributions"]), len(snapshot["events"]), len(snapshot["repos"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError) as exc:
        LOG.error("GitHub fetch failed: %s", exc)
        return 1


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
