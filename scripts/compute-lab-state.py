"""Turn data/snapshot.json into durable lab states and write data/lab-state.json.

Every GitHub event becomes a state (activity, condition, mode, machines), never a one-shot moment.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import sys

from lab_common import CONFIG_PATH, LOG, SNAPSHOT_PATH, STATE_PATH, read_json, setup_logging, six_month_start, write_json


MACHINE_WINDOW_DAYS = 14
EVENT_LABELS = {
    "PushEvent": "PUSH",
    "PullRequestEvent": "PR",
    "PullRequestReviewEvent": "REVIEW",
    "IssuesEvent": "ISSUE",
    "IssueCommentEvent": "COMMENT",
    "CreateEvent": "CREATE",
    "ReleaseEvent": "RELEASE",
    "ForkEvent": "FORK",
    "WatchEvent": "STAR",
}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_events(snapshot: dict, now: datetime, days: int) -> list[dict]:
    """Accept both trimmed events ("repo": "owner/name") and raw API events ("repo": {"name": ...})."""
    since = now - timedelta(days=days)
    events = []
    for event in snapshot.get("events", []):
        try:
            repo = event["repo"]
            full = repo["name"] if isinstance(repo, dict) else repo
            created = parse_time(event["created_at"])
            if not full or not since <= created <= now:
                continue
            owner, _, name = str(full).rpartition("/")
            events.append({
                "type": str(event.get("type", "")),
                "action": str(event.get("action") or (event.get("payload") or {}).get("action") or ""),
                "merged": bool(event.get("merged")),
                "size": max(1, int(event.get("size") or 1)),
                "owner": owner,
                "repo": name,
                "created": created,
            })
        except (KeyError, TypeError, ValueError, AttributeError):
            LOG.warning("Skipping malformed public event")
    events.sort(key=lambda item: item["created"], reverse=True)
    return events


def display_name(repo: str, config: dict, limit: int) -> str:
    return str(config.get("focus_aliases", {}).get(repo, repo)).upper()[:limit]


def machine_slots(config: dict) -> int:
    """The bay floor fits at most five machines."""
    return min(5, max(1, int(config.get("machine_slots", 5))))


def compute_machines(snapshot: dict, events: list[dict], config: dict, now: datetime) -> list[dict]:
    """One machine per recently active repo; energy 1-4 follows its share of the work."""
    ignored = set(config.get("ignore_repos", []))
    slots = machine_slots(config)
    languages = {repo.get("name"): repo.get("language") for repo in snapshot.get("repos", []) if isinstance(repo, dict)}
    weight: Counter = Counter()
    last: dict[str, datetime] = {}
    for event in events:
        if event["repo"] in ignored:
            continue
        weight[event["repo"]] += event["size"] if event["type"] == "PushEvent" else 1
        last.setdefault(event["repo"], event["created"])
    since = now - timedelta(days=MACHINE_WINDOW_DAYS)
    for repo in snapshot.get("repos", []):
        try:
            name = repo["name"]
            if name in ignored or name in weight or repo.get("fork") or repo.get("archived") or not repo.get("pushed_at"):
                continue
            pushed = parse_time(repo["pushed_at"])
            if since <= pushed <= now:
                weight[name] += 1
                last[name] = pushed
        except (KeyError, TypeError, ValueError, AttributeError):
            LOG.warning("Skipping malformed repository entry")
    ranked = sorted(weight, key=lambda name: (-weight[name], -last[name].timestamp(), name))[:slots]
    top = max((weight[name] for name in ranked), default=1)
    return [
        {
            "repo": name,
            "label": display_name(name, config, 13),
            "language": str(languages.get(name) or "MIXED").upper()[:10],
            "work": weight[name],
            "energy": max(1, math.ceil(4 * weight[name] / top)),
            "last_active": last[name].date().isoformat(),
        }
        for name in ranked
    ]


def log_lines(events: list[dict], config: dict, limit: int = 8) -> list[str]:
    lines = []
    for event in events[:limit]:
        label = EVENT_LABELS.get(event["type"], event["type"].removesuffix("Event").upper()[:7])
        if event["type"] == "PullRequestEvent":
            label = "MERGE" if event["merged"] else f"PR {event['action'][:6].upper()}".strip()
        detail = f"x{event['size']}" if event["type"] == "PushEvent" else ""
        lines.append(f"{event['created']:%m-%d} {label:<9} {display_name(event['repo'], config, 14):<14} {detail}".rstrip())
    return lines


def compute_state(snapshot: dict, config: dict, now: datetime) -> dict:
    today = now.date()
    start = six_month_start(today)
    counts = {}
    for item in snapshot.get("contributions", []):
        try:
            day = date.fromisoformat(item["date"])
            count = int(item["count"])
            if count < 0:
                raise ValueError("negative contribution count")
            if start <= day <= today:
                counts[day] = count
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid contribution day: {item!r}") from exc
    if not counts:
        raise RuntimeError(f"No contribution history in {start} through {today}")
    days = []
    cursor = start
    while cursor <= today:
        days.append({"date": cursor.isoformat(), "count": counts.get(cursor, 0)})
        cursor += timedelta(days=1)
    last_week = sum(item["count"] for item in days[-7:])
    if last_week <= config["idle_max_contributions_7d"]:
        activity = "SLEEPING"
    elif last_week <= config["tinkering_max_contributions_7d"]:
        activity = "TINKERING"
    elif last_week <= config["building_max_contributions_7d"]:
        activity = "BUILDING"
    else:
        activity = "OVERCLOCKED"

    recent = normalize_events(snapshot, now, 7)
    frequencies = Counter(event["repo"] for event in recent)
    focus = next(
        (event["repo"] for event in recent if frequencies[event["repo"]] == max(frequencies.values(), default=0)),
        config["profile_repo"],
    )
    focus = display_name(focus, config, 22)

    failed = snapshot.get("workflow") in {"failure", "timed_out", "action_required"}
    if failed:
        condition = "CRITICAL" if activity == "OVERCLOCKED" else "WARNING"
    else:
        condition = "ENERGIZED" if activity == "OVERCLOCKED" else "STABLE"

    owner = str(config.get("username", "")).lower()
    shipped = any(
        event["type"] == "ReleaseEvent" or (event["type"] == "PullRequestEvent" and event["merged"])
        for event in recent
    )
    machines = compute_machines(snapshot, normalize_events(snapshot, now, MACHINE_WINDOW_DAYS), config, now)
    if shipped:
        mode = "SHIPPING"
    elif owner and any(event["owner"].lower() != owner for event in recent):
        mode = "OPEN-SOURCE"
    elif len(machines) >= 3 or any(event["type"] == "CreateEvent" for event in recent):
        mode = "EXPERIMENTING"
    else:
        mode = "RESEARCH"

    return {
        "activity": activity,
        "condition": condition,
        "mode": mode,
        "focus": focus,
        "machines": machines,
        "machine_slots": machine_slots(config),
        "log": log_lines(normalize_events(snapshot, now, MACHINE_WINDOW_DAYS), config),
        "repos_touched_7d": len(frequencies),
        "prs_7d": sum(event["type"] == "PullRequestEvent" for event in recent),
        "workflow": str(snapshot.get("workflow") or "unknown"),
        "days": days,
        "total_6mo": sum(item["count"] for item in days),
        "active_days": sum(item["count"] > 0 for item in days),
        "contributions_7d": last_week,
        "contributions_24h": days[-1]["count"],
        "peak_day": max(item["count"] for item in days),
        "start": start,
        "end": today,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    parser.add_argument("--output", type=Path, default=STATE_PATH)
    args = parser.parse_args()
    try:
        state = compute_state(read_json(args.snapshot), read_json(CONFIG_PATH), datetime.now(timezone.utc))
        write_json(args.output, state)
        LOG.info("Wrote %s: %s / %s / %s, %s machines", args.output,
                 state["activity"], state["condition"], state["mode"], len(state["machines"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Lab state computation failed: %s", exc)
        return 1


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
