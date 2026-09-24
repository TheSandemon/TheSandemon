"""Render data/lab-state.json as the animated build facility in assets/lab.svg.

Every animation repeats indefinitely and the first frame is readable on its own.
"""

from __future__ import annotations

import argparse
from datetime import date
import math
from pathlib import Path
import sys
from xml.sax.saxutils import escape

from lab_common import LOG, STATE_PATH, SVG_PATH, read_json, setup_logging


CHART_WIDTH = 552
DAY_WIDTH = 5
MACHINE_PITCH = 210
MACHINE_WIDTH = 180
LOG_ROWS = 9
LOG_LINE = 16

# Environmental palette follows system condition.
PALETTES = {
    "STABLE": {"accent": "#7ee8b0", "glow": "#c8ffa2", "lamp": "#7ee8b0", "label": "ALL GOOD"},
    "ENERGIZED": {"accent": "#c6f76a", "glow": "#efffb0", "lamp": "#c6f76a", "label": "EXTRA SPICY"},
    "WARNING": {"accent": "#ffb347", "glow": "#ffe0a0", "lamp": "#ff8f5a", "label": "GREMLIN DETECTED"},
    "CRITICAL": {"accent": "#ff6b5e", "glow": "#ffc2a8", "lamp": "#ff4b4b", "label": "CONTAINMENT BREACH"},
}
# Loop speed, cable flow and ambient light follow activity.
TEMPO = {
    "SLEEPING": {"pulse": 4.8, "flow": 3.2, "ambient": 0.04, "mood": "PROBABLY PLOTTING"},
    "TINKERING": {"pulse": 3.6, "flow": 2.2, "ambient": 0.1, "mood": "IDEAS IN THE OVEN"},
    "BUILDING": {"pulse": 2.4, "flow": 1.4, "ambient": 0.16, "mood": "MAKING IT REAL"},
    "OVERCLOCKED": {"pulse": 1.4, "flow": 0.8, "ambient": 0.22, "mood": "SEND SNACKS"},
}
MONO = 'font-family="monospace"'


def fmt(seconds: float) -> str:
    return f"{seconds:.2f}".rstrip("0").rstrip(".") + "s"


def anim(attribute: str, values: str, dur: float) -> str:
    return f'<animate attributeName="{attribute}" values="{values}" dur="{fmt(dur)}" repeatCount="indefinite"/>'


def chase(index: int, count: int, dur: float) -> str:
    """Opacity loop whose bright frame is rotated per light, so a row of lights chases seamlessly."""
    frames = [".25"] * count
    frames[index % count] = "1"
    return anim("opacity", ";".join(frames + frames[:1]), dur)


def text(x: float, y: float, body: str, size: int = 10, fill: str = "#f3ebc7", extra: str = "") -> str:
    return f'<text x="{x}" y="{y}" fill="{fill}" {MONO} font-size="{size}" {extra}>{escape(body)}</text>'


def as_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def chart_markup(days: list[dict], x: int = 224, y: int = 100) -> str:
    positive = sorted(day["count"] for day in days if day["count"] > 0)
    cap = max(1, positive[min(len(positive) - 1, int(len(positive) * 0.95))] if positive else 1)
    points = [
        (index * DAY_WIDTH, round(137 - math.sqrt(min(day["count"], cap) / cap) * 108, 1))
        for index, day in enumerate(days)
    ]
    period = len(days) * DAY_WIDTH
    points.append((period, points[0][1]))
    line = "M" + " L".join(f"{px} {py}" for px, py in points)
    area = f"{line} L{period} 139 L0 139Z"
    marks = []
    for index, item in enumerate(days):
        day = date.fromisoformat(item["date"])
        if day.day == 1 or index == 0:
            mx = index * DAY_WIDTH
            marks.append(
                f'<path d="M{mx} 6V143" stroke="#4a7770" stroke-width="1" stroke-dasharray="3 6" opacity=".55"/>'
                f'<text x="{mx + 5}" y="155" fill="#89b9a8" {MONO} font-size="10">{day.strftime("%b").upper()}</text>'
            )
    segment = (
        f'<path d="{area}" fill="url(#chartFill)" opacity=".68"/>'
        f'<path d="{line}" fill="none" stroke="#c8ffa2" stroke-width="3" stroke-linecap="square" stroke-linejoin="miter"/>'
        f'<path d="{line}" fill="none" stroke="#aaf5b9" stroke-width="9" opacity=".13"/>'
        + "".join(marks)
    )
    offset = max(0, period - CHART_WIDTH)
    return (
        f'<g transform="translate({x} {y})" clip-path="url(#chartClip)" shape-rendering="geometricPrecision">'
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


def hud_markup(state: dict, palette: dict, tempo: dict) -> str:
    beacon_dur = tempo["pulse"] / (3 if state["condition"] in {"WARNING", "CRITICAL"} else 1)
    boxes = [
        (360, 160, "ACTIVITY", state["activity"]),
        (528, 192, "SYSTEM", palette["label"]),
        (728, 128, "MODE", state["mode"]),
        (864, 200, "OUTPUT", f'{state["contributions_7d"]} THIS WEEK · {state["contributions_24h"]} TODAY'),
    ]
    parts = [
        '<rect x="16" y="10" width="1048" height="42" fill="#10292b" stroke="#4c8371" stroke-width="2"/>',
        f'<rect x="26" y="24" width="12" height="12" fill="{palette["lamp"]}">{anim("opacity", "1;.2;1", beacon_dur)}</rect>',
        text(48, 36, "SANDEMON'S LAB // BUILD FACILITY", 14, "#f3ebc7", 'font-weight="bold"'),
    ]
    for x, width, label, value in boxes:
        parts.append(f'<rect x="{x}" y="16" width="{width}" height="30" fill="#0a1d20" stroke="#2f5a55" stroke-width="2"/>')
        parts.append(text(x + 8, 27, label, 8, "#7fae9c", 'font-weight="bold" letter-spacing="1"'))
        parts.append(text(x + 8, 41, value, 11, palette["glow"] if label == "SYSTEM" else "#f3ebc7", 'font-weight="bold"'))
    return "".join(parts)


def reactor_markup(state: dict, palette: dict, tempo: dict) -> str:
    accent, glow, pulse = palette["accent"], palette["glow"], tempo["pulse"]
    hazard = state["condition"] in {"WARNING", "CRITICAL"}
    parts = [
        '<rect x="16" y="62" width="180" height="206" fill="#14302f" stroke="#5e9483" stroke-width="3"/>',
        '<rect x="16" y="62" width="180" height="26" fill="#1c3f3b"/>',
        text(26, 80, "REACTOR CORE", 11, "#f3ebc7", 'font-weight="bold"'),
        f'<rect x="170" y="70" width="16" height="10" fill="{palette["lamp"]}">{anim("opacity", "1;.15;1", pulse / (3 if hazard else 1))}</rect>',
        # Glass chamber with a stepped, blocky glow.
        '<rect x="56" y="96" width="100" height="118" fill="#061518" stroke="#3f7a70" stroke-width="4"/>',
        f'<rect x="64" y="104" width="84" height="102" fill="{accent}" opacity=".12">{anim("opacity", ".08;.24;.08", pulse)}</rect>',
        f'<rect x="76" y="116" width="60" height="78" fill="{accent}" opacity=".3">{anim("opacity", ".22;.45;.22", pulse)}</rect>',
        f'<rect x="88" y="128" width="36" height="54" fill="{glow}" opacity=".75">{anim("opacity", ".6;1;.6", pulse)}</rect>',
        '<rect x="100" y="140" width="12" height="30" fill="#ffffff" opacity=".7"/>',
    ]
    # Plasma bars rising through the chamber at slightly different rates.
    for index, width in enumerate((52, 36, 68)):
        parts.append(
            f'<rect x="{106 - width // 2}" y="200" width="{width}" height="4" fill="{glow}" opacity=".5">'
            + anim("y", "202;100", pulse * (1.3 + index * 0.37)) + "</rect>"
        )
    # Coolant tubes with bubbles.
    for tx, liquid in ((26, "#4fd2a0"), (166, "#c48ba8")):
        parts.append(f'<rect x="{tx}" y="104" width="20" height="104" fill="#0c2226" stroke="#6ea79a" stroke-width="2"/>')
        parts.append(f'<rect x="{tx + 2}" y="150" width="16" height="56" fill="{liquid}" opacity=".7"/>')
        for bubble in range(2):
            parts.append(
                f'<rect x="{tx + 6 + bubble * 5}" y="200" width="4" height="4" fill="#e8fff0">'
                + anim("y", "202;152", 2.1 + bubble * 0.9 + tx / 200)
                + anim("opacity", "0;1;0", 2.1 + bubble * 0.9 + tx / 200) + "</rect>"
            )
    # Vent lights chase along the base.
    for index in range(6):
        parts.append(f'<rect x="{34 + index * 24}" y="224" width="16" height="8" fill="{accent}">{chase(index, 6, pulse)}</rect>')
    if hazard:
        stripes = "".join(
            f'<path d="M{x} 256l8-12h8l-8 12Z" fill="#f2c14e"/>' for x in range(24, 184, 16)
        )
        parts.append(f'<rect x="22" y="244" width="168" height="12" fill="#1a1a14"/><g>{stripes}</g>')
    else:
        parts.append(text(26, 254, f'{state["total_6mo"]:,} / 6MO OUTPUT', 10, "#9fcbb8", 'font-weight="bold"'))
    return "".join(parts)


def monitor_markup(state: dict, palette: dict) -> str:
    start = as_date(state["start"]).strftime("%b %d").upper()
    end = as_date(state["end"]).strftime("%b %d").upper()
    stats = f'{state["total_6mo"]:,} CONTRIBUTIONS · {state["active_days"]} ACTIVE DAYS · BEST DAY {state["peak_day"]}'
    grid = "".join(f'<path d="M224 {100 + gy}H776" stroke="#1d4a50" stroke-width="1"/>' for gy in (29, 65, 101, 137))
    return (
        '<rect x="208" y="62" width="592" height="206" fill="#2a4f4b" stroke="#88b59b" stroke-width="3"/>'
        '<rect x="214" y="68" width="580" height="194" fill="#082328"/>'
        + text(224, 86, "OUTPUT HISTORY", 12, "#b7f1b0", 'font-weight="bold" letter-spacing="2"')
        + text(368, 86, f"{start} — {end}", 10, "#82b9ac")
        + text(766, 86, stats, 10, "#e8e8c9", 'text-anchor="end"')
        + grid
        + chart_markup(state["days"])
        + f'<rect x="776" y="80" width="8" height="8" fill="{palette["accent"]}">{anim("opacity", "1;.2;1", 1.2)}</rect>'
    )


def log_markup(state: dict, palette: dict) -> str:
    events = list(state.get("log") or []) or ["-- NO PUBLIC SIGNAL --"]
    # Sparse weeks are padded with system readouts rather than repeated events.
    status = [
        f'CORE      {state["activity"]}',
        f'SYSTEM    {state["condition"]}',
        f'MODE      {state["mode"]}',
        f'BAYS      {len(state["machines"])} ONLINE',
        f'6MO       {state["total_6mo"]:,} CONTRIB',
        f'ACTIVE    {state["active_days"]} DAYS',
    ]
    lines = events + ["-" * 30] + status[: max(0, LOG_ROWS - len(events))]
    count = len(lines)
    rows = "".join(
        text(822, 110 + index * LOG_LINE, line, 10, "#aee8c4" if line in events else "#6f9f90", 'xml:space="preserve"')
        for index, line in enumerate(lines + lines)
    )
    return (
        '<rect x="812" y="62" width="252" height="206" fill="#1d3a39" stroke="#6e9c8c" stroke-width="3"/>'
        '<rect x="818" y="68" width="240" height="194" fill="#051417"/>'
        + text(824, 86, "BUILD LOG", 12, "#f3ebc7", 'font-weight="bold" letter-spacing="2"')
        + text(1050, 86, f'{state["workflow"].upper()[:10]}', 9, palette["glow"], 'text-anchor="end"')
        + '<path d="M818 92H1058" stroke="#24514d" stroke-width="2"/>'
        + '<g clip-path="url(#logClip)"><g>'
        + f'<animateTransform attributeName="transform" type="translate" from="0 0" to="0 -{count * LOG_LINE}" '
        f'dur="{fmt(count * 2.2)}" repeatCount="indefinite"/>'
        + rows + "</g></g>"
        + '<path d="M818 244H1058" stroke="#24514d" stroke-width="2"/>'
        + text(824, 257, "$ watch --forever", 10, "#c8ffa2")
        + f'<rect x="930" y="248" width="7" height="11" fill="{palette["glow"]}">{anim("opacity", "1;1;0;0", 1.1)}</rect>'
    )


def machine_markup(index: int, machine: dict | None, palette: dict, tempo: dict) -> str:
    x0 = 31 + index * MACHINE_PITCH
    cx = x0 + MACHINE_WIDTH // 2
    online = machine is not None
    body, rim = ("#2d4c4b", "#6e9c8c") if online else ("#1a2d2e", "#34514f")
    parts = [
        # Power drop from the bus; live drops carry moving energy.
        f'<path d="M{cx} 290V322" stroke="#0c1c1e" stroke-width="10"/>',
        f'<rect x="{x0}" y="404" width="{MACHINE_WIDTH}" height="10" fill="#0b1a1c"/>',
        f'<rect x="{x0 + 8}" y="322" width="{MACHINE_WIDTH - 16}" height="82" fill="{body}" stroke="{rim}" stroke-width="3"/>',
        f'<rect x="{x0 + 18}" y="330" width="144" height="32" fill="#061518" stroke="#24514d" stroke-width="2"/>',
    ]
    if not online:
        parts += [
            text(x0 + 26, 345, "BAY OFFLINE", 11, "#56736d", 'font-weight="bold"'),
            text(x0 + 26, 357, "AWAITING REPO", 8, "#46615b"),
            f'<rect x="{x0 + 146}" y="308" width="12" height="8" fill="#6b3a36">{anim("opacity", ".35;.8;.35", 6)}</rect>',
            "".join(f'<rect x="{x0 + 18 + k * 12}" y="370" width="8" height="10" fill="#203634"/>' for k in range(4)),
            f'<rect x="{x0 + 122}" y="368" width="34" height="30" fill="#1f3332"/>',
        ]
        return "".join(parts)
    energy = int(machine["energy"])
    speed = tempo["flow"] * (1.6 - energy * 0.2)
    parts += [
        f'<path d="M{cx} 290V322" stroke="{palette["accent"]}" stroke-width="{2 + energy}" stroke-dasharray="6 6">'
        f'{anim("stroke-dashoffset", "12;0", speed)}</path>',
        text(x0 + 26, 345, machine["label"], 11, "#f3ebc7", 'font-weight="bold"'),
        text(x0 + 26, 357, f'{machine["language"]} · {machine["work"]} UNITS · {machine["last_active"][5:]}', 8, "#86bea9"),
        f'<rect x="{x0 + 146}" y="308" width="12" height="8" fill="{palette["lamp"]}">{anim("opacity", "1;.3;1", tempo["pulse"])}</rect>',
        f'<rect x="{x0 + 20}" y="333" width="140" height="2" fill="{palette["glow"]}" opacity=".18">'
        f'{anim("y", "333;358;333", 3.4 + index * 0.3)}</rect>',
    ]
    for k in range(4):
        fill = palette["accent"] if k < energy else "#203634"
        light = chase(k, 4, tempo["pulse"]) if k < energy else ""
        parts.append(f'<rect x="{x0 + 18 + k * 12}" y="370" width="8" height="10" fill="{fill}">{light}</rect>')
    # Piston stamping onto a moving conveyor.
    parts += [
        f'<rect x="{x0 + 122}" y="366" width="34" height="8" fill="#4d7470"/>',
        f'<rect x="{x0 + 133}" y="374" width="12" height="12" fill="#9fc4b6">'
        f'{anim("height", "6;16;6", speed * 1.5)}</rect>',
        f'<path d="M{x0 + 18} 396H{x0 + 162}" stroke="#0c1c1e" stroke-width="6"/>',
        f'<path d="M{x0 + 18} 396H{x0 + 162}" stroke="{palette["glow"]}" stroke-width="2" stroke-dasharray="4 8" opacity=".6">'
        f'{anim("stroke-dashoffset", "12;0", speed * 1.2)}</path>',
        text(x0 + 70, 379, f"LV{energy}", 8, "#9fcbb8", 'font-weight="bold"'),
    ]
    return "".join(parts)


def bay_markup(state: dict, palette: dict, tempo: dict) -> str:
    slots = min(5, max(1, int(state.get("machine_slots", 5))))
    machines = list(state.get("machines") or [])[:slots]
    live_end = 31 + (len(machines) - 1) * MACHINE_PITCH + MACHINE_WIDTH // 2 if machines else 106
    last_center = 31 + (slots - 1) * MACHINE_PITCH + MACHINE_WIDTH // 2
    parts = [
        # Power bus from the reactor across the bay.
        '<path d="M106 268V290" stroke="#0c1c1e" stroke-width="12"/>',
        f'<path d="M100 290H{last_center + 6}" stroke="#0c1c1e" stroke-width="12"/>',
        f'<path d="M106 268V290H{live_end}" fill="none" stroke="{palette["accent"]}" stroke-width="4" '
        f'stroke-dasharray="8 8" opacity=".9">{anim("stroke-dashoffset", "16;0", tempo["flow"])}</path>',
    ]
    for index in range(slots):
        parts.append(machine_markup(index, machines[index] if index < len(machines) else None, palette, tempo))
    summary = (
        f'FOCUS {state["focus"]} · {len(machines)}/{slots} BAYS ONLINE · '
        f'{state["repos_touched_7d"]} REPOS 7D · {state["prs_7d"]} PR EVENTS 7D · {tempo["mood"]}'
    )
    parts.append(text(540, 431, summary, 10, "#cae2be", 'text-anchor="middle" font-weight="bold"'))
    return "".join(parts)


def render_svg(state: dict) -> str:
    state = {**state, "mode": state.get("mode", "RESEARCH"), "machines": state.get("machines", []),
             "log": state.get("log", []), "repos_touched_7d": state.get("repos_touched_7d", 0),
             "prs_7d": state.get("prs_7d", 0), "workflow": state.get("workflow", "unknown")}
    palette = PALETTES.get(state["condition"], PALETTES["STABLE"])
    tempo = TEMPO.get(state["activity"], TEMPO["TINKERING"])
    activity = state["activity"]
    ambient = tempo["ambient"]
    flicker = anim("opacity", f"{ambient};{ambient * 0.6:.3f};{ambient}", tempo["pulse"] * 2)
    lamps = "".join(
        f'<path d="M{x} 54h24l30 360H{x - 30}Z" fill="{palette["glow"]}" opacity="{ambient}">{flicker}</path>'
        for x in (190, 530, 870)
    )
    online = len(state["machines"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="440" viewBox="0 0 1080 440" role="img" aria-labelledby="title desc">
<title id="title">Sandemon's Lab build facility — {activity.lower()}</title>
<desc id="desc">An animated build facility with no people in it. A reactor core powers {online} active machine bays, one per recently active repository, through cables whose energy flow follows GitHub activity. A monitor scrolls {len(state["days"])} days of contributions from {as_date(state["start"])} to {as_date(state["end"])} (total {state["total_6mo"]}), and a build log cycles recent events. State: {activity}, {state["condition"]}, {state["mode"]}.</desc>
<defs>
  <linearGradient id="chartFill" x2="0" y2="1"><stop stop-color="#a8f2a4" stop-opacity=".45"/><stop offset="1" stop-color="#46a682" stop-opacity=".03"/></linearGradient>
  <pattern id="bricks" width="32" height="16" patternUnits="userSpaceOnUse"><rect width="32" height="16" fill="#0c2023"/><path d="M0 15H32M15 0V7M31 8V15" stroke="#132d30" stroke-width="2"/></pattern>
  <pattern id="tiles" width="24" height="24" patternUnits="userSpaceOnUse"><rect width="24" height="24" fill="#10262a"/><rect width="12" height="12" fill="#132d31"/><rect x="12" y="12" width="12" height="12" fill="#132d31"/></pattern>
  <pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#000"/></pattern>
  <clipPath id="chartClip"><rect width="{CHART_WIDTH}" height="160"/></clipPath>
  <clipPath id="logClip"><rect x="818" y="96" width="240" height="146"/></clipPath>
</defs>
<g shape-rendering="crispEdges">
<rect width="1080" height="440" fill="url(#bricks)"/>
<rect x="0" y="414" width="1080" height="26" fill="url(#tiles)"/>
<path d="M0 414H1080" stroke="#3f7a6a" stroke-width="4"/>
{lamps}
{hud_markup(state, palette, tempo)}
{reactor_markup(state, palette, tempo)}
{monitor_markup(state, palette)}
{log_markup(state, palette)}
{bay_markup(state, palette, tempo)}
<rect width="1080" height="440" fill="url(#scan)" opacity=".08" pointer-events="none"/>
<rect x="0" y="0" width="1080" height="6" fill="{palette["glow"]}" opacity=".05">{anim("y", "0;434;0", 12)}</rect>
<rect x="1" y="1" width="1078" height="438" fill="none" stroke="#588878" stroke-width="2"/>
</g>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--output", type=Path, default=SVG_PATH)
    args = parser.parse_args()
    try:
        state = read_json(args.state)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(render_svg(state), encoding="utf-8")
        LOG.info("Generated %s: %s, %s machines online", args.output, state["activity"], len(state.get("machines", [])))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as exc:
        LOG.error("Lab rendering failed: %s", exc)
        return 1


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
