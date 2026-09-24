"""Generate the README lab from public GitHub activity. Uses only Python stdlib."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("sandemon.lab")
ACTIVE_TYPES = {"PushEvent", "PullRequestEvent", "CreateEvent", "ReleaseEvent"}


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read JSON from {path}: {exc}") from exc


def api_get(url: str, token: str | None) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "sandemon-profile-lab"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def fetch_snapshot(config: dict, token: str | None) -> dict:
    user = quote(config["username"], safe="")
    repo = quote(config["profile_repo"], safe="")
    events = []
    for page in (1, 2):
        batch = api_get(f"https://api.github.com/users/{user}/events/public?per_page=100&page={page}", token)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub public events response was not a list")
        events.extend(batch)
        if len(batch) < 100:
            break
    workflow = "unknown"
    try:
        runs = api_get(
            f"https://api.github.com/repos/{user}/{repo}/actions/runs?status=completed&per_page=1", token
        )
        if isinstance(runs, dict) and runs.get("workflow_runs"):
            workflow = str(runs["workflow_runs"][0].get("conclusion") or "unknown")
    except RuntimeError as exc:
        # Activity still renders when Actions history is unavailable.
        LOG.warning("Workflow status unavailable: %s", exc)
    return {"events": events, "workflow": workflow}


def compute_state(snapshot: dict, config: dict, now: datetime) -> dict:
    week_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)
    recent = []
    for event in snapshot.get("events", []):
        try:
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            if week_ago <= created <= now:
                recent.append((event, created))
        except (KeyError, TypeError, ValueError, AttributeError):
            LOG.warning("Skipping malformed public event")
    active = [(event, created) for event, created in recent if event.get("type") in ACTIVE_TYPES]
    count = len(active)
    if count <= config["quiet_max_events_7d"]:
        activity = "SLEEPING"
    elif count <= config["tinkering_max_events_7d"]:
        activity = "TINKERING"
    elif count <= config["building_max_events_7d"]:
        activity = "BUILDING"
    else:
        activity = "OVERCLOCKED"
    repos = Counter(
        event.get("repo", {}).get("name", "").split("/")[-1]
        for event, _ in active
        if event.get("repo", {}).get("name")
    )
    # On ties, prefer the repo with the most recent qualifying event.
    focus = next((event["repo"]["name"].split("/")[-1] for event, _ in active
                  if repos.get(event.get("repo", {}).get("name", "").split("/")[-1]) == max(repos.values(), default=0)),
                 config["profile_repo"])
    focus = config.get("focus_aliases", {}).get(focus, focus).upper()[:20]
    failed = snapshot.get("workflow") in {"failure", "timed_out", "action_required"}
    condition = "WARNING" if failed else "ENERGIZED" if activity == "OVERCLOCKED" else "STABLE"
    return {
        "activity": activity,
        "condition": condition,
        "focus": focus,
        "events_7d": count,
        "events_24h": sum(created >= day_ago for _, created in active),
        "repos_7d": len(repos),
    }


def render_svg(state: dict) -> str:
    activity = state["activity"]
    condition = state["condition"]
    active = activity in {"BUILDING", "OVERCLOCKED"}
    fast = activity == "OVERCLOCKED"
    accent = "#fb7864" if condition == "WARNING" else "#b7f36b" if fast else "#70e0b3"
    pulse = "1.1s" if fast else "2s" if active else "3.4s" if activity == "TINKERING" else "5s"
    hand_motion = "0.38s" if fast else "0.7s" if active else "3s"
    status_detail = "CHECK SYSTEMS" if condition == "WARNING" else "FULL POWER" if fast else "NOMINAL"
    focus = escape(str(state["focus"]))
    events_7d = int(state["events_7d"])
    events_24h = int(state["events_24h"])
    repos_7d = int(state["repos_7d"])
    # Every animation below repeats indefinitely. The first frame is a complete static scene.
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="360" viewBox="0 0 960 360" role="img" aria-labelledby="title desc">
<title id="title">Sandemon's Lab — {activity.lower()}</title>
<desc id="desc">Pixel-art scientist in an emerald circuit suit. Lab status {activity.lower()}, system {condition.lower()}, current experiment {focus}.</desc>
<rect width="960" height="360" fill="#09171a"/>
<path d="M0 0H960V360H0Z" fill="none" stroke="#244d48" stroke-width="4"/>
<rect x="12" y="12" width="936" height="42" fill="#102b2b" stroke="#3a7161" stroke-width="2"/>
<rect x="26" y="26" width="10" height="10" fill="{accent}"/>
<text x="47" y="39" fill="#e9e4bc" font-family="monospace" font-size="18" font-weight="bold" letter-spacing="2">SANDEMON'S LAB</text>
<text x="432" y="38" fill="#83bba4" font-family="monospace" font-size="12" letter-spacing="1">LIVE FROM THE WORKSHOP</text>
<rect x="763" y="22" width="169" height="24" fill="#183b37" stroke="{accent}" stroke-width="2"/>
<circle cx="778" cy="34" r="5" fill="{accent}"><animate attributeName="opacity" values="1;.35;1" dur="{pulse}" repeatCount="indefinite"/></circle>
<text x="792" y="39" fill="#e9e4bc" font-family="monospace" font-size="12" font-weight="bold">{activity}</text>

<!-- Skyline window: a nod to the sunset rooftop in the reference portrait. -->
<rect x="28" y="70" width="240" height="180" fill="#1f3441" stroke="#639084" stroke-width="4"/>
<rect x="38" y="80" width="220" height="160" fill="#564c60"/>
<rect x="38" y="80" width="220" height="61" fill="#ad776e"/>
<rect x="38" y="130" width="220" height="42" fill="#e6a174"/>
<rect x="198" y="104" width="28" height="28" fill="#f9d28a"/>
<path d="M38 195h20v-42h20v22h18v-56h18v15h12v-28h20v38h16v-20h18v34h16v-49h22v30h18v-18h22v76H38Z" fill="#253c45"/>
<path d="M38 216h27v-44h20v26h16v-31h20v49h16v-21h24v21h16v-47h24v25h18v-32h39v54H38Z" fill="#172b34"/>
<path d="M54 183h5m41 2h5m42-19h5m49 8h5m-115 29h5m83-13h5" stroke="#e8bf83" stroke-width="3"/>
<path d="M38 119H258M148 80V240" stroke="#183b3e" stroke-width="5"/>
<rect x="29" y="250" width="238" height="8" fill="#375e56"/>

<!-- Lab wall, floor, and cabinet. -->
<path d="M275 69H933V265H275Z" fill="#0f2429"/>
<path d="M275 83H933M275 124H933M275 165H933M275 206H933M275 247H933" stroke="#17343a" stroke-width="2"/>
<path d="M301 68V258M586 68V258M831 68V258" stroke="#1b3e42" stroke-width="3"/>
<rect x="20" y="261" width="920" height="77" fill="#15302f"/>
<path d="M20 262H940" stroke="#477866" stroke-width="6"/>
<path d="M20 289H940M20 316H940" stroke="#285048" stroke-width="2"/>
<path d="M79 265V337M158 265V337M237 265V337M316 265V337M395 265V337M474 265V337M553 265V337M632 265V337M711 265V337M790 265V337M869 265V337" stroke="#285048" stroke-width="2"/>

<!-- Scientist: dark hair, trimmed beard, emerald suit and gold circuit embroidery. -->
<g id="scientist" shape-rendering="crispEdges">
  <animateTransform attributeName="transform" type="translate" values="0 0;0 1;0 0" dur="{pulse}" repeatCount="indefinite"/>
  <rect x="326" y="195" width="92" height="67" fill="#075844"/>
  <rect x="333" y="202" width="78" height="55" fill="#08745a"/>
  <rect x="336" y="210" width="19" height="7" fill="#d6b46e"/>
  <path d="M341 217v22h15m45-22v22h-15m-30-29 16 22 16-22" fill="none" stroke="#d6b46e" stroke-width="3"/>
  <path d="M372 212l-7 13 7 26 7-26Z" fill="#b79954" stroke="#f0d283" stroke-width="2"/>
  <path d="M372 223v21m-4-11h8" stroke="#5c753e" stroke-width="2"/>
  <rect x="352" y="164" width="40" height="42" fill="#c48b69"/>
  <rect x="347" y="171" width="8" height="22" fill="#b47c5f"/>
  <rect x="391" y="171" width="8" height="22" fill="#b47c5f"/>
  <path d="M350 172v-19h8v-8h29v6h9v22h-8v-10h-30v9Z" fill="#18201f"/>
  <rect x="354" y="175" width="34" height="19" fill="#d2a07b"/>
  <path d="M355 190h7v5h20v-5h7v10h-8v6h-19v-6h-7Z" fill="#3b302b"/>
  <path d="M362 181h6m13 0h6" stroke="#27312e" stroke-width="3"/>
  <rect x="365" y="186" width="3" height="2" fill="#f1c9a0"/>
  <path d="M368 196h10" stroke="#a97d63" stroke-width="2"/>
  <rect x="319" y="209" width="19" height="45" fill="#09644e"/>
  <rect x="406" y="209" width="18" height="43" fill="#09644e"/>
  <path d="M325 218v22h7m79-22v18h7" fill="none" stroke="#b79d5d" stroke-width="2"/>
  <rect x="410" y="241" width="19" height="10" fill="#b98868">
    <animate attributeName="y" values="241;244;241" dur="{hand_motion}" repeatCount="indefinite"/>
  </rect>
  <rect x="319" y="250" width="18" height="9" fill="#b98868"/>
</g>

<!-- Workstation and two monitors. -->
<rect x="434" y="155" width="148" height="91" fill="#234b49" stroke="#6a9d7f" stroke-width="4"/>
<rect x="443" y="164" width="130" height="69" fill="#092b2d"/>
<text x="452" y="181" fill="{accent}" font-family="monospace" font-size="10" font-weight="bold">CURRENT EXPERIMENT</text>
<text x="452" y="201" fill="#e5e6b7" font-family="monospace" font-size="13" font-weight="bold">{focus}</text>
<path d="M451 215h72" stroke="#4bbaa1" stroke-width="3"/>
<rect x="527" y="211" width="6" height="7" fill="{accent}"><animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/></rect>
<rect x="492" y="246" width="30" height="13" fill="#38605b"/>
<rect x="459" y="259" width="97" height="5" fill="#6f9d79"/>
<rect x="598" y="113" width="88" height="64" fill="#234b49" stroke="#6a9d7f" stroke-width="4"/>
<rect x="605" y="120" width="74" height="49" fill="#0a2930"/>
<path d="M611 146h10l5-12 7 23 6-13h8l4-8 6 13h15" fill="none" stroke="{accent}" stroke-width="3"/>
<path d="M605 127H679" stroke="#477977" stroke-width="2"><animate attributeName="y1" values="127;162;127" dur="4s" repeatCount="indefinite"/><animate attributeName="y2" values="127;162;127" dur="4s" repeatCount="indefinite"/></path>
<rect x="631" y="177" width="20" height="14" fill="#38605b"/>

<!-- Emerald reactor. Persistent pulse and circulating energy. -->
<rect x="700" y="103" width="173" height="149" fill="#163639" stroke="#5d8e7a" stroke-width="5"/>
<path d="M720 123h132v108H720Z" fill="#0a262d" stroke="#3f766c" stroke-width="3"/>
<path d="M766 131h38l27 45-27 45h-38l-27-45Z" fill="#1d6f5d" stroke="{accent}" stroke-width="5"/>
<path d="M773 144h25l20 32-20 32h-25l-20-32Z" fill="#278d6e" opacity=".55"><animate attributeName="opacity" values=".4;.85;.4" dur="{pulse}" repeatCount="indefinite"/></path>
<circle cx="785" cy="176" r="24" fill="{accent}" opacity=".25"><animate attributeName="r" values="22;31;22" dur="{pulse}" repeatCount="indefinite"/></circle>
<circle cx="785" cy="176" r="17" fill="{accent}"><animate attributeName="opacity" values=".7;1;.7" dur="{pulse}" repeatCount="indefinite"/></circle>
<path d="M785 142v-13m0 94v-13m-47-34h-12m118 0h-12" stroke="{accent}" stroke-width="4" stroke-dasharray="6 4"><animate attributeName="stroke-dashoffset" values="0;-20" dur="{pulse}" repeatCount="indefinite"/></path>
<rect x="703" y="236" width="170" height="18" fill="#28584e"/>
<text x="720" y="249" fill="#e9e4bc" font-family="monospace" font-size="10" font-weight="bold">REACTOR / {status_detail}</text>

<!-- Beakers and warning lamp. -->
<path d="M68 262v-37h-6v-5h29v5h-6v37Z" fill="#286a66" stroke="#8ac8a7" stroke-width="3"/>
<path d="M68 241h17v20H68Z" fill="#60dbac"/>
<circle cx="74" cy="230" r="3" fill="#9af4c3"><animate attributeName="cy" values="239;218;239" dur="2.2s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;0" dur="2.2s" repeatCount="indefinite"/></circle>
<circle cx="82" cy="232" r="2" fill="#9af4c3"><animate attributeName="cy" values="243;216;243" dur="2.9s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;0" dur="2.9s" repeatCount="indefinite"/></circle>
<path d="M107 262v-28h-5v-5h28v5h-5v28Z" fill="#675066" stroke="#b58da0" stroke-width="3"/>
<path d="M107 248h18v13h-18Z" fill="#c47d9d"/>
<circle cx="117" cy="238" r="2" fill="#f4b7c8"><animate attributeName="cy" values="249;225;249" dur="3.3s" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;0" dur="3.3s" repeatCount="indefinite"/></circle>
<rect x="893" y="122" width="23" height="15" fill="{accent}"><animate attributeName="opacity" values="1;.25;1" dur="{pulse}" repeatCount="indefinite"/></rect>
<rect x="898" y="137" width="13" height="29" fill="#46675b"/>

<!-- Readable game-style HUD. -->
<rect x="28" y="278" width="226" height="48" fill="#0b2728" stroke="#548477" stroke-width="2"/>
<text x="40" y="295" fill="#79bda1" font-family="monospace" font-size="10" font-weight="bold">PUBLIC SIGNAL / 7 DAYS</text>
<text x="40" y="314" fill="#e9e4bc" font-family="monospace" font-size="12">{events_7d:02d} EVENTS  ·  {repos_7d:02d} REPOS</text>
<rect x="278" y="278" width="310" height="48" fill="#0b2728" stroke="#548477" stroke-width="2"/>
<text x="290" y="295" fill="#79bda1" font-family="monospace" font-size="10" font-weight="bold">LAB MODE / {condition}</text>
<text x="290" y="314" fill="#e9e4bc" font-family="monospace" font-size="12">{events_24h:02d} SIGNALS IN 24H · IDLE LOOP ACTIVE</text>
<rect x="612" y="278" width="309" height="48" fill="#0b2728" stroke="#548477" stroke-width="2"/>
<text x="624" y="295" fill="#79bda1" font-family="monospace" font-size="10" font-weight="bold">WORKSHOP TRANSMISSION</text>
<text x="624" y="314" fill="#e9e4bc" font-family="monospace" font-size="12">MAKE WEIRD THINGS WORK.</text>
<text x="29" y="351" fill="#6da393" font-family="monospace" font-size="9">THE SANDEMON // PIXEL LAB V1</text>
<text x="866" y="351" fill="#6da393" font-family="monospace" font-size="9">∞ LOOP</text>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot with events and workflow")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "lab.svg")
    args = parser.parse_args()
    try:
        config = read_json(ROOT / "config" / "lab.json")
        snapshot = read_json(args.fixture) if args.fixture else fetch_snapshot(config, os.getenv("GITHUB_TOKEN"))
        state = compute_state(snapshot, config, datetime.now(timezone.utc))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_svg(state), encoding="utf-8")
        LOG.info("Generated %s: %s", args.output, state)
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Lab generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
