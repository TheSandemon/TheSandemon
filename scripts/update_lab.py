"""Render a six-month GitHub contribution history as Sandemon's animated lab."""

from __future__ import annotations

import argparse
import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
import logging
import math
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("sandemon.lab")
GRAPHQL_URL = "https://api.github.com/graphql"
CHART_WIDTH = 552
DAY_WIDTH = 5
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


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top-level value must be an object")
        return value
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Cannot read JSON from {path}: {exc}") from exc


def six_month_start(today: date) -> date:
    month_index = today.year * 12 + today.month - 1 - 6
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


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
    events = []
    workflow = "unknown"
    try:
        recent = request_json(f"https://api.github.com/users/{user}/events/public?per_page=100", token)
        if isinstance(recent, list):
            events = recent
    except RuntimeError as exc:
        LOG.warning("Current experiment unavailable: %s", exc)
    try:
        runs = request_json(
            f"https://api.github.com/repos/{user}/{repo}/actions/runs?status=completed&per_page=1", token
        )
        if isinstance(runs, dict) and runs.get("workflow_runs"):
            workflow = str(runs["workflow_runs"][0].get("conclusion") or "unknown")
    except RuntimeError as exc:
        LOG.warning("System condition unavailable: %s", exc)
    return {"contributions": contributions, "events": events, "workflow": workflow}


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
        activity = "IDLE"
    elif last_week <= config["tinkering_max_contributions_7d"]:
        activity = "TINKERING"
    elif last_week <= config["building_max_contributions_7d"]:
        activity = "BUILDING"
    else:
        activity = "OVERCLOCKED"
    recent_events = []
    week_ago = now - timedelta(days=7)
    for event in snapshot.get("events", []):
        try:
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if week_ago <= created <= now and event.get("repo", {}).get("name"):
                recent_events.append((event["repo"]["name"].split("/")[-1], created))
        except (KeyError, TypeError, ValueError, AttributeError):
            LOG.warning("Skipping malformed public event")
    frequencies = Counter(repo for repo, _ in recent_events)
    focus = next(
        (repo for repo, _ in sorted(recent_events, key=lambda entry: entry[1], reverse=True)
         if frequencies[repo] == max(frequencies.values(), default=0)),
        config["profile_repo"],
    )
    focus = config.get("focus_aliases", {}).get(focus, focus).upper()[:22]
    condition = (
        "WARNING" if snapshot.get("workflow") in {"failure", "timed_out", "action_required"}
        else "ENERGIZED" if activity == "OVERCLOCKED" else "STABLE"
    )
    return {
        "activity": activity,
        "condition": condition,
        "focus": focus,
        "days": days,
        "total_6mo": sum(item["count"] for item in days),
        "active_days": sum(item["count"] > 0 for item in days),
        "contributions_7d": last_week,
        "contributions_24h": days[-1]["count"],
        "peak_day": max(item["count"] for item in days),
        "start": start,
        "end": today,
    }


def chart_markup(days: list[dict]) -> str:
    positive = sorted(day["count"] for day in days if day["count"] > 0)
    cap = max(1, positive[min(len(positive) - 1, int(len(positive) * 0.95))] if positive else 1)
    points = [
        (index * DAY_WIDTH, round(137 - math.sqrt(min(day["count"], cap) / cap) * 108, 1))
        for index, day in enumerate(days)
    ]
    period = len(days) * DAY_WIDTH
    points.append((period, points[0][1]))
    line = "M" + " L".join(f"{x} {y}" for x, y in points)
    area = f"{line} L{period} 139 L0 139Z"
    marks = []
    for index, item in enumerate(days):
        day = date.fromisoformat(item["date"])
        if day.day == 1 or index == 0:
            label = day.strftime("%b").upper()
            x = index * DAY_WIDTH
            marks.append(
                f'<path d="M{x} 6V143" stroke="#4a7770" stroke-width="1" stroke-dasharray="3 6" opacity=".55"/>'
                f'<text x="{x + 5}" y="157" fill="#89b9a8" font-family="monospace" font-size="10">{label}</text>'
            )
    segment = (
        f'<path d="{area}" fill="url(#chartFill)" opacity=".68"/>'
        f'<path d="{line}" fill="none" stroke="#c8ffa2" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<path d="{line}" fill="none" stroke="#aaf5b9" stroke-width="9" opacity=".13" stroke-linejoin="round"/>'
        + "".join(marks)
    )
    offset = max(0, period - CHART_WIDTH)
    return (
        '<g transform="translate(264 143)" clip-path="url(#chartClip)">'
        '<g>'
        f'<animateTransform attributeName="transform" type="translate" from="-{offset} 0" '
        f'to="-{offset + period} 0" dur="38s" repeatCount="indefinite"/>'
        + segment
        + f'<g transform="translate({period} 0)">{segment}</g>'
        + '</g>'
        '<rect x="-18" y="0" width="18" height="139" fill="#d9ffb5" opacity=".12">'
        '<animate attributeName="x" values="-18;570" dur="7s" repeatCount="indefinite"/>'
        '</rect></g>'
    )


def skyline_markup() -> str:
    buildings = [(0, 123, 26, 82), (24, 101, 34, 104), (57, 136, 25, 69),
                 (80, 82, 31, 123), (110, 113, 35, 92), (144, 75, 30, 130),
                 (173, 110, 24, 95)]
    shapes = []
    windows = []
    for number, (x, y, width, height) in enumerate(buildings):
        shapes.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="#213940"/>')
        for wx in range(x + 6, x + width - 4, 10):
            for wy in range(y + 11, 198, 15):
                if (wx + wy + number) % 3:
                    windows.append(
                        f'<rect x="{wx}" y="{wy}" width="3" height="5" rx="1" fill="#ffd690" opacity=".8"/>'
                    )
    return (
        '<g transform="translate(26 81)" clip-path="url(#windowClip)">'
        '<rect width="194" height="204" fill="url(#sunset)"/>'
        '<circle cx="142" cy="62" r="23" fill="#ffe3a2" opacity=".8"/>'
        '<path d="M0 151Q82 126 194 151V205H0Z" fill="#51616b" opacity=".52"/>'
        + "".join(shapes) + "".join(windows)
        + '<path d="M0 205H194" stroke="#122c32" stroke-width="9"/>'
        '</g>'
    )


def render_svg(state: dict) -> str:
    activity = state["activity"]
    condition = state["condition"]
    mood = {
        "IDLE": "PROBABLY PLOTTING",
        "TINKERING": "IDEAS IN THE OVEN",
        "BUILDING": "MAKING IT REAL",
        "OVERCLOCKED": "SEND SNACKS",
    }[activity]
    system = {"STABLE": "ALL GOOD", "ENERGIZED": "EXTRA SPICY", "WARNING": "GREMLIN DETECTED"}[condition]
    accent = "#ff927b" if condition == "WARNING" else "#bdf798" if condition == "ENERGIZED" else "#8be5bd"
    pulse = "1.4s" if activity == "OVERCLOCKED" else "2.4s" if activity == "BUILDING" else "3.6s"
    focus = escape(str(state["focus"]))
    start = state["start"].strftime("%b %d").upper()
    end = state["end"].strftime("%b %d").upper()
    graph = chart_markup(state["days"])
    skyline = skyline_markup()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="440" viewBox="0 0 1080 440" role="img" aria-labelledby="title desc">
<title id="title">Sandemon's Lab — {activity.lower()}</title>
<desc id="desc">An animated laboratory with a scrolling line of {len(state["days"])} daily GitHub contribution counts, from {state["start"]} to {state["end"]}. Six-month total: {state["total_6mo"]}. A reactor, glassware, and sunset skyline surround the archive.</desc>
<defs>
  <linearGradient id="room" x2="0" y2="1"><stop stop-color="#122f32"/><stop offset="1" stop-color="#071a21"/></linearGradient>
  <linearGradient id="sunset" x2="0" y2="1"><stop stop-color="#665674"/><stop offset=".55" stop-color="#ecaa85"/><stop offset="1" stop-color="#f4c796"/></linearGradient>
  <linearGradient id="chartFill" x2="0" y2="1"><stop stop-color="#a8f2a4" stop-opacity=".45"/><stop offset="1" stop-color="#46a682" stop-opacity=".03"/></linearGradient>
  <radialGradient id="core"><stop stop-color="#f1ffba"/><stop offset=".5" stop-color="{accent}"/><stop offset="1" stop-color="#177b69"/></radialGradient>
  <clipPath id="windowClip"><rect width="194" height="204" rx="9"/></clipPath>
  <clipPath id="chartClip"><rect width="{CHART_WIDTH}" height="167" rx="5"/></clipPath>
</defs>
<rect width="1080" height="440" rx="18" fill="url(#room)"/>
<rect x="2" y="2" width="1076" height="436" rx="17" fill="none" stroke="#588878" stroke-width="3"/>
<path d="M0 355H1080" stroke="#55967b" stroke-width="5"/>
<path d="M0 361H1080V440H0Z" fill="#102c30"/>
<path d="M0 386H1080M0 417H1080" stroke="#1d4646" stroke-width="2"/>
<rect x="18" y="15" width="1044" height="47" rx="10" fill="#163a3a" stroke="#4c8371" stroke-width="2"/>
<circle cx="40" cy="39" r="6" fill="{accent}"><animate attributeName="opacity" values="1;.4;1" dur="{pulse}" repeatCount="indefinite"/></circle>
<text x="58" y="46" fill="#f3ebc7" font-family="monospace" font-size="20" font-weight="bold" letter-spacing="2">SANDEMON'S LAB</text>
<text x="468" y="45" fill="#a3d3ba" font-family="monospace" font-size="12" letter-spacing="2">LITTLE IDEAS, BIG EXPERIMENTS</text>
<rect x="873" y="26" width="171" height="27" rx="13" fill="#275449" stroke="{accent}" stroke-width="2"/>
<text x="892" y="44" fill="#f0eed0" font-family="monospace" font-size="12" font-weight="bold">{activity} · {state["contributions_7d"]} THIS WEEK</text>

<!-- Sunset window; every lit window is drawn within its building. -->
<rect x="22" y="77" width="202" height="212" rx="12" fill="#183d42" stroke="#8bb9a2" stroke-width="4"/>
{skyline}
<path d="M123 81V285M26 185H220" stroke="#2a5556" stroke-width="6"/>
<path d="M34 294h178" stroke="#6b9d88" stroke-width="5" stroke-linecap="round"/>
<text x="35" y="315" fill="#aed2b7" font-family="monospace" font-size="10" font-weight="bold">CITY LIGHTS</text>
<text x="35" y="330" fill="#aed2b7" font-family="monospace" font-size="10" font-weight="bold">LAB NIGHTS</text>
<path d="M184 337v-27m0 17q-14-21-21-24m21 16q11-20 21-21" fill="none" stroke="#6fa987" stroke-width="4" stroke-linecap="round"/>
<ellipse cx="166" cy="302" rx="10" ry="6" fill="#4b9d74" transform="rotate(28 166 302)"/>
<ellipse cx="202" cy="298" rx="11" ry="6" fill="#51a475" transform="rotate(-26 202 298)"/>
<path d="M170 337h29l-4 13h-21Z" fill="#bb9374" stroke="#d4b18b" stroke-width="2"/>

<!-- The six-month archive is the visual centerpiece. -->
<rect x="239" y="76" width="600" height="277" rx="16" fill="#2b5652" stroke="#88b59b" stroke-width="4"/>
<rect x="249" y="86" width="580" height="257" rx="10" fill="#092a30"/>
<path d="M259 133H819M259 313H819" stroke="#35635e" stroke-width="2"/>
<text x="265" y="111" fill="#b7f1b0" font-family="monospace" font-size="13" font-weight="bold" letter-spacing="2">THE LONG GAME</text>
<text x="265" y="127" fill="#82b9ac" font-family="monospace" font-size="10">EVERY DAY HAS A STORY</text>
<text x="649" y="111" fill="#e8e8c9" font-family="monospace" font-size="12" font-weight="bold">{start} — {end}</text>
<text x="682" y="127" fill="#82b9ac" font-family="monospace" font-size="10">SIX MONTHS</text>
<path d="M264 280H816M264 238H816M264 196H816M264 154H816" stroke="#24525a" stroke-width="1"/>
{graph}
<text x="264" y="333" fill="#f3ebc7" font-family="monospace" font-size="12" font-weight="bold">{state["total_6mo"]:,} SPARKS</text>
<text x="410" y="333" fill="#93c1ae" font-family="monospace" font-size="12">{state["active_days"]} ACTIVE DAYS</text>
<text x="613" y="333" fill="#93c1ae" font-family="monospace" font-size="12">BEST DAY {state["peak_day"]}</text>
<circle cx="812" cy="104" r="4" fill="{accent}"><animate attributeName="r" values="4;6;4" dur="{pulse}" repeatCount="indefinite"/></circle>

<!-- A smaller, lively reactor and gently wobbling glassware. -->
<path d="M867 160h173v192H867Z" fill="#14383c" stroke="#679b85" stroke-width="4"/>
<rect x="881" y="174" width="146" height="151" rx="12" fill="#082b32" stroke="#39776d" stroke-width="3"/>
<circle cx="954" cy="244" r="56" fill="#256e65" opacity=".15"><animate attributeName="r" values="51;61;51" dur="{pulse}" repeatCount="indefinite"/></circle>
<circle cx="954" cy="244" r="45" fill="none" stroke="{accent}" stroke-width="5" stroke-dasharray="16 12"><animate attributeName="stroke-dashoffset" values="0;-56" dur="5s" repeatCount="indefinite"/></circle>
<circle cx="954" cy="244" r="30" fill="url(#core)"><animate attributeName="r" values="28;34;28" dur="{pulse}" repeatCount="indefinite"/></circle>
<path d="M954 184v-15m0 136v-15m-60-46h-14m148 0h-14" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
<circle cx="954" cy="244" r="11" fill="#f0ffd0" opacity=".72"><animate attributeName="opacity" values=".55;.9;.55" dur="{pulse}" repeatCount="indefinite"/></circle>
<path d="M891 331h126" stroke="#83b393" stroke-width="5" stroke-linecap="round"/>
<text x="900" y="347" fill="#cae2be" font-family="monospace" font-size="10" font-weight="bold">REACTOR / {system}</text>
<path d="M874 141h164" stroke="#6b9f8b" stroke-width="5" stroke-linecap="round"/>
<g transform="translate(895 91)">
  <animateTransform attributeName="transform" type="rotate" values="-2 18 51;2 18 51;-2 18 51" dur="3s" additive="sum" repeatCount="indefinite"/>
  <path d="M11 0h15m-12 0v18L4 45q-2 7 6 7h20q8 0 6-7L25 18V0" fill="#235856" stroke="#8ed4bd" stroke-width="3"/>
  <path d="M9 36h23l5 12H4Z" fill="#72ddb0" opacity=".8"/>
  <circle cx="18" cy="29" r="3" fill="#d6ffbd"><animate attributeName="cy" values="36;22;36" dur="2.7s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;0" dur="2.7s" repeatCount="indefinite"/></circle>
</g>
<g transform="translate(964 98)">
  <animateTransform attributeName="transform" type="rotate" values="2 16 44;-2 16 44;2 16 44" dur="3.4s" additive="sum" repeatCount="indefinite"/>
  <path d="M8 0h17m-13 0v22L4 41q-2 7 5 7h24q7 0 5-7L29 22V0" fill="#2c5860" stroke="#9bd2cb" stroke-width="3"/>
  <path d="M7 34h28l4 10H3Z" fill="#c48ba8" opacity=".85"/>
  <circle cx="19" cy="26" r="2.8" fill="#f2c2cf"><animate attributeName="cy" values="32;17;32" dur="3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;0" dur="3s" repeatCount="indefinite"/></circle>
</g>

<!-- Short, human labels keep the atmosphere playful. -->
<rect x="20" y="373" width="311" height="51" rx="10" fill="#173d3c" stroke="#4d8674" stroke-width="2"/>
<text x="34" y="391" fill="#86bea9" font-family="monospace" font-size="10" font-weight="bold">LAB MOOD</text>
<text x="34" y="410" fill="#f3ebc7" font-family="monospace" font-size="14" font-weight="bold">{activity} · {mood}</text>
<rect x="343" y="373" width="390" height="51" rx="10" fill="#173d3c" stroke="#4d8674" stroke-width="2"/>
<text x="357" y="391" fill="#86bea9" font-family="monospace" font-size="10" font-weight="bold">CURRENT EXPERIMENT</text>
<text x="357" y="410" fill="#f3ebc7" font-family="monospace" font-size="14" font-weight="bold">{focus}</text>
<rect x="745" y="373" width="315" height="51" rx="10" fill="#173d3c" stroke="#4d8674" stroke-width="2"/>
<text x="759" y="391" fill="#86bea9" font-family="monospace" font-size="10" font-weight="bold">TODAY / SYSTEM</text>
<text x="759" y="410" fill="#f3ebc7" font-family="monospace" font-size="14" font-weight="bold">{state["contributions_24h"]} SPARKS · {system}</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot with contributions, events and workflow")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "lab.svg")
    args = parser.parse_args()
    try:
        config = read_json(ROOT / "config" / "lab.json")
        now = datetime.now(timezone.utc)
        snapshot = read_json(args.fixture) if args.fixture else fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""), now)
        state = compute_state(snapshot, config, now)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_svg(state), encoding="utf-8")
        LOG.info(
            "Generated %s: %s, %s contributions across %s days",
            args.output, state["activity"], state["total_6mo"], len(state["days"]),
        )
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Lab generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
