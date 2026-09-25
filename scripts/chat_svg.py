"""Render a scripted conversation as one endlessly typing, dark-mode agent chat SVG.

Pure SMIL, no script, so it plays inside GitHub's image proxy. Text streams in word by word
behind per-line cover rects whose x steps to each word's measured end. The fonts are embedded,
so those measurements match what the viewer sees. The conversation scrolls as it grows. A static
copy of the finished conversation sits above the live one, so when the loop restarts the screen
looks exactly as it did at the end and the seam is invisible.

Conversation steps (tuples):
  ("user", text)                        typed into the input box, then sent as a bubble
  ("think", seconds)                    "Thinking..." that collapses to "Thought for Ns"
  ("tool", live_label, done_label)      a tool call row that collapses to its result
  ("say", [segments, ...])              paragraphs; segments are (text, style) with style r/b/m
  ("bullets", [segments, ...])          a bulleted list, streamed like paragraphs
  ("code", header, [(a, b, c), ...])    a monospace card whose rows land one by one
  ("stats", [(number, label), ...])     up to four stat tiles
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
import random
import unicodedata
from xml.sax.saxutils import escape


FONT_DIR = Path(__file__).resolve().parent / "fonts"
METRICS = json.loads((FONT_DIR / "metrics.json").read_text(encoding="utf-8"))
FACES = {"r": "sans-regular", "b": "sans-bold", "m": "mono-regular"}
FAMILY = {
    "r": 'font-family="SandSans, Arial, Helvetica, sans-serif"',
    "b": 'font-family="SandSans, Arial, Helvetica, sans-serif" font-weight="700"',
    "m": "font-family=\"SandMono, 'Courier New', monospace\"",
}

W, H = 880, 640
VIEW_TOP, VIEW_BOTTOM = 56, 560
PAD, GAP = 24, 26
TX, TMAX = 80, 740
SIZE, MONO, LH = 15, 14, 24
BG, PANEL, LINE = "#171717", "#1f1f1f", "#2c2c2c"
INK, DIM, FAINT = "#ececec", "#9b9b9b", "#6b6b6b"
BUBBLE, CODE, AVATAR_BG, AVATAR_RING = "#2a2a2a", "#111111", "#2a2418", "#4a3b17"


def safe(text: str) -> str:
    """Keep only characters the embedded fonts can draw, folding accents and dropping the rest."""
    known = METRICS["sans-regular"]
    out = []
    for ch in text:
        if ch in known:
            out.append(ch)
            continue
        folded = "".join(c for c in unicodedata.normalize("NFKD", ch) if c in known)
        out.append(folded)
    return "".join(out)


def width(text: str, style: str = "r", size: float | None = None) -> float:
    size = size or (MONO if style == "m" else SIZE)
    table = METRICS[FACES[style]]
    return sum(table.get(ch, 0.55) for ch in text) * size


def fit_width(text: str, style: str, size: float, limit: float) -> str:
    text = safe(text)
    if width(text, style, size) <= limit:
        return text
    while text and width(text + "…", style, size) > limit:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap_segments(segments: list[tuple[str, str]], limit: float) -> list[list[tuple[str, str, float]]]:
    """Split styled segments into lines of (token, style, x) that fit `limit`, one token per word."""
    tokens = []
    for text, style in segments:
        parts = safe(text).split(" ")
        for i, part in enumerate(parts):
            token = part + (" " if i < len(parts) - 1 else "")
            if token:
                tokens.append((token, style))
    lines, line, x = [], [], 0.0
    for token, style in tokens:
        if line and x + width(token.rstrip(), style) > limit:
            lines.append(line)
            line, x = [], 0.0
        if not line and not token.strip():
            continue
        line.append((token, style, x))
        x += width(token, style)
    if line:
        lines.append(line)
    return lines


# ----------------------------------------------------------------- timeline

def layout(steps: list[tuple], seed: int = 7) -> tuple[list[dict], list[tuple[float, float]], list[tuple], float, float]:
    """Place every step in content space and on the clock. Returns items, scroll keys, inputs, height, cycle."""
    rng = random.Random(seed)
    t, y = 0.8, 0.0
    items, scroll, inputs = [], [(0.0, 0.0)], []
    avatar_due = True

    def reveal(at: float, bottom: float) -> None:
        if bottom > scroll[-1][1] + 0.5:
            scroll.append((at, scroll[-1][1]))
            scroll.append((at + 0.22, bottom))

    def stream(lines: list, x0: float, bullet: bool) -> None:
        nonlocal t, y
        for index, line in enumerate(lines):
            t += 0.05
            stamps = []
            for token, style, x in line:
                t += rng.uniform(0.05, 0.12)
                word = token.rstrip()
                if word.endswith((".", ":", "?", "!")):
                    t += rng.uniform(0.18, 0.35)
                elif word.endswith((",", ";")):
                    t += rng.uniform(0.06, 0.14)
                stamps.append((t, x + width(word, style)))
            start = stamps[0][0] - 0.06
            items.append({"kind": "line", "y": y, "x0": x0, "tokens": line, "stamps": stamps,
                          "t0": start, "t1": t, "dot": bullet and index == 0})
            reveal(start, y + LH)
            y += LH

    for step in steps:
        kind = step[0]
        if kind == "user":
            text = fit_width(step[1], "r", SIZE, 520)
            t += 1.2
            y += GAP - 10
            start, stamps = t, []
            for ch in text:
                t += rng.uniform(0.045, 0.11) + (0.12 if ch == " " and rng.random() < 0.15 else 0)
                stamps.append(t)
            t += 0.45
            inputs.append((start, t, text, stamps))
            items.append({"kind": "bubble", "y": y, "t0": t, "text": text, "w": width(text) + 32})
            reveal(t, y + 42)
            y += 42 + GAP
            avatar_due = True
        elif kind in ("think", "tool"):
            t0 = t + 0.25
            seconds = float(step[1]) if kind == "think" else rng.uniform(1.1, 1.6)
            live = "Thinking" if kind == "think" else step[1]
            done = f"Thought for {max(1, round(seconds))}s" if kind == "think" else step[2]
            items.append({"kind": kind, "y": y, "t0": t0, "t1": t0 + seconds, "avatar": avatar_due,
                          "live": fit_width(live, "r", 14, TMAX - 40), "done": fit_width(done, "r", 14, TMAX - 40)})
            avatar_due = False
            reveal(t0, y + 26)
            t = t0 + seconds
            y += 36
        elif kind == "say":
            for paragraph in step[1]:
                stream(wrap_segments(paragraph, TMAX), TX, False)
                t += 0.35
                y += 10
            t += 0.3
        elif kind == "bullets":
            for bullet in step[1]:
                stream(wrap_segments(bullet, TMAX - 22), TX + 22, True)
                t += 0.25
                y += 6
            y += 4
            t += 0.3
        elif kind == "code":
            rows = step[2]
            height = 46 + len(rows) * 22
            t0 = t + 0.2
            t = t0
            row_times = []
            for _ in rows:
                t += rng.uniform(0.28, 0.45)
                row_times.append(t)
            items.append({"kind": "code", "y": y, "h": height, "header": step[1], "rows": rows, "t0": t0, "row_t": row_times})
            reveal(t0, y + height)
            y += height + 12
            t += 0.4
        elif kind == "stats":
            cells = step[1][:4]
            t0 = t + 0.2
            t = t0
            cell_times = []
            for _ in cells:
                t += rng.uniform(0.25, 0.4)
                cell_times.append(t)
            items.append({"kind": "stats", "y": y, "h": 74, "cells": cells, "t0": t0, "cell_t": cell_times})
            reveal(t0, y + 74)
            y += 86
            t += 0.3
        else:
            raise ValueError(f"Unknown conversation step: {kind}")
    # Reading time, then one small scroll so the end lines up with the start exactly.
    t += 3.0
    scroll.append((t - 0.4, scroll[-1][1]))
    scroll.append((t, y))
    return items, scroll, inputs, y, t


# ------------------------------------------------------------------ markup

def key_times(times: list[float], cycle: float) -> str:
    return ";".join(f"{min(max(t / cycle, 0.0), 1.0):.5f}".rstrip("0").rstrip(".") or "0" for t in times)


def discrete(attribute: str, pairs: list[tuple[float, object]], cycle: float, initial: object) -> str:
    """Hold `initial` from the start of every cycle, then each (time, value) until the next."""
    pairs = [(t, v) for t, v in pairs if 0 < t < cycle]
    times = [0.0] + [t for t, _ in pairs]
    values = [initial] + [v for _, v in pairs]
    return (f'<animate attributeName="{attribute}" calcMode="discrete" values="{";".join(map(str, values))}" '
            f'keyTimes="{key_times(times, cycle)}" dur="{cycle:.2f}s" repeatCount="indefinite"/>')


def shown(start: float, end: float | None, cycle: float) -> str:
    return discrete("opacity", [(start, 1)] + ([(end, 0)] if end is not None else []), cycle, 0)


def spark(cx: float, cy: float, r: float, fill: str, extra: str = "") -> str:
    points = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        radius = r if i % 2 == 0 else r * 0.32
        points.append(f"{cx + radius * math.cos(angle):.1f},{cy + radius * math.sin(angle):.1f}")
    return f'<polygon points="{" ".join(points)}" fill="{fill}">{extra}</polygon>'


def text_el(x: float, y: float, value: str, style: str = "r", size: float | None = None, fill: str = INK,
            extra: str = "") -> str:
    size = size or (MONO if style == "m" else SIZE)
    return (f'<text x="{x:.1f}" y="{y:.1f}" {FAMILY[style]} font-size="{size:g}" fill="{fill}"{extra}>'
            f"{escape(value)}</text>")


def render_items(items: list[dict], cycle: float, accent: str, live: bool) -> str:
    out = []
    for item in items:
        y = item["y"]
        kind = item["kind"]
        if kind == "bubble":
            x = W - 40 - item["w"]
            bubble = (f'<rect x="{x:.1f}" y="{y:.1f}" width="{item["w"]:.1f}" height="42" rx="18" fill="{BUBBLE}"/>'
                      + text_el(x + 16, y + 26, item["text"]))
            out.append(f'<g opacity="0">{shown(item["t0"], None, cycle)}{bubble}</g>' if live else bubble)
        elif kind in ("think", "tool"):
            cy = y + 13
            avatar = (f'<circle cx="52" cy="{cy:.1f}" r="14" fill="{AVATAR_BG}" stroke="{AVATAR_RING}"/>'
                      + spark(52, cy, 8, accent)) if item["avatar"] else ""
            icon = (f'<circle cx="{TX + 5}" cy="{cy:.1f}" r="3" fill="{FAINT}"/>' if kind == "think"
                    else f'<path d="M{TX} {cy:.1f}l4 4 7-8" stroke="{FAINT}" stroke-width="2" fill="none"/>')
            done = icon + text_el(TX + 18, cy + 5, f'{item["done"]}  ›', "r", 14, FAINT)
            if not live:
                out.append(avatar + done)
                continue
            spin = (f'<animateTransform attributeName="transform" type="rotate" values="0 {TX + 6} {cy:.1f};'
                    f'360 {TX + 6} {cy:.1f}" dur="1.4s" repeatCount="indefinite"/>')
            working = spark(TX + 6, cy, 7, accent, spin) + text_el(TX + 18, cy + 5, f'{item["live"]}…', "r", 14, "url(#shimmer)")
            if avatar:
                out.append(f'<g opacity="0">{shown(item["t0"], None, cycle)}{avatar}</g>')
            out.append(f'<g opacity="0">{shown(item["t0"], item["t1"], cycle)}{working}</g>')
            out.append(f'<g opacity="0">{shown(item["t1"], None, cycle)}{done}</g>')
        elif kind == "line":
            x0 = item["x0"]
            words = "".join(
                text_el(x0 + x, y + 17, token, style, fill=accent if style == "m" else INK, extra=' xml:space="preserve"')
                for token, style, x in item["tokens"]
            )
            if item["dot"]:
                words = f'<circle cx="{x0 - 12}" cy="{y + 12:.1f}" r="2.6" fill="{DIM}"/>' + words
            if not live:
                out.append(words)
                continue
            steps = [(t, round(x0 + x + 1, 1)) for t, x in item["stamps"]]
            cover = (f'<rect x="{x0 - 16}" y="{y:.1f}" width="{W}" height="{LH}" fill="{BG}">'
                     f"{discrete('x', steps, cycle, x0 - 16)}</rect>")
            caret = (f'<rect x="{x0}" y="{y + 5:.1f}" width="8" height="15" rx="2" fill="{accent}" opacity="0">'
                     f"{discrete('x', [(t, x + 3) for t, x in steps], cycle, x0)}"
                     f"{shown(item['t0'], item['t1'] + 0.05, cycle)}</rect>")
            out.append(words + cover + caret)
        elif kind == "code":
            first_w = max([width(row[0], "m", 13) for row in item["rows"]] + [0])
            middle_x = TX + 14 + (first_w + 18 if first_w else 0)
            message_x = middle_x + max([width(row[1], "m", 13) for row in item["rows"]] + [0]) + 16
            box = (f'<rect x="{TX}" y="{y:.1f}" width="{TMAX}" height="{item["h"]}" rx="10" fill="{CODE}" stroke="{LINE}"/>'
                   + text_el(TX + 14, y + 22, fit_width(item["header"], "m", 12, TMAX - 28), "m", 12, FAINT)
                   + f'<path d="M{TX} {y + 32:.1f}H{TX + TMAX}" stroke="{LINE}"/>')
            rows = []
            for i, (left, middle, right) in enumerate(item["rows"]):
                ry = y + 54 + i * 22
                row = (text_el(TX + 14, ry, left, "m", 13, FAINT) + text_el(middle_x, ry, middle, "m", 13, accent)
                       + text_el(message_x, ry, fit_width(right, "m", 13, TX + TMAX - 14 - message_x), "m", 13))
                rows.append(f'<g opacity="0">{shown(item["row_t"][i], None, cycle)}{row}</g>' if live else row)
            out.append((f'<g opacity="0">{shown(item["t0"], None, cycle)}{box}</g>' if live else box) + "".join(rows))
        elif kind == "stats":
            count = len(item["cells"])
            cell_w = (TMAX - (count - 1) * 10) / count
            for i, (number, label) in enumerate(item["cells"]):
                cx = TX + i * (cell_w + 10)
                cell = (f'<rect x="{cx:.1f}" y="{y:.1f}" width="{cell_w:.1f}" height="74" rx="10" fill="{PANEL}" stroke="{LINE}"/>'
                        + text_el(cx + 16, y + 38, fit_width(str(number), "b", 26, cell_w - 24), "b", 26)
                        + text_el(cx + 16, y + 60, fit_width(label, "r", 13, cell_w - 24), "r", 13, DIM))
                out.append(f'<g opacity="0">{shown(item["cell_t"][i], None, cycle)}{cell}</g>' if live else cell)
    return "".join(out)


def font_css() -> str:
    faces = [("SandSans", 400, "sans-regular"), ("SandSans", 700, "sans-bold"), ("SandMono", 400, "mono-regular")]
    return "".join(
        f"@font-face{{font-family:{family};font-weight:{weight};"
        f"src:url(data:font/woff2;base64,{base64.b64encode((FONT_DIR / f'{name}.woff2').read_bytes()).decode()}) format('woff2')}}"
        for family, weight, name in faces
    )


def render(steps: list[tuple], *, name: str, tagline: str, synced: str, placeholder: str, footer: str,
           accent: str, title: str, desc: str) -> str:
    items, scroll, inputs, total, cycle = layout(steps)
    base = VIEW_BOTTOM - PAD
    times, values = [], []
    for t, offset in scroll + [(cycle, total)]:
        if times and t <= times[-1]:
            t = times[-1] + 0.001
        times.append(t)
        values.append(base - offset)
    scroll_anim = (f'<animateTransform attributeName="transform" type="translate" '
                   f'values="{";".join(f"0 {v:.1f}" for v in values)}" keyTimes="{key_times(times, cycle)}" '
                   f'dur="{cycle:.2f}s" repeatCount="indefinite"/>')
    history = f'<g transform="translate(0 {-total:.1f})">{render_items(items, cycle, accent, False)}</g>'
    conversation = render_items(items, cycle, accent, True)

    iy = 578
    typing = [(start, end) for start, end, _, _ in inputs]
    idle = [pair for start, end in typing for pair in ((start, 0), (end, 1))]
    send = [pair for start, end in typing for pair in ((start + 0.1, 1), (end, 0))]
    box = [
        f'<rect x="24" y="{iy}" width="{W - 48}" height="46" rx="14" fill="{PANEL}" stroke="{LINE}"/>',
        f'<g>{discrete("opacity", idle, cycle, 1)}'
        f'<rect x="44" y="{iy + 15}" width="2" height="17" fill="{INK}">'
        f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>'
        + text_el(52, iy + 28, fit_width(placeholder, "r", SIZE, W - 160), fill=FAINT) + "</g>",
    ]
    for start, end, question, stamps in inputs:
        steps_x = [(t, round(44 + width(question[: i + 1]), 1)) for i, t in enumerate(stamps)]
        box.append(
            f'<g opacity="0">{shown(start, end, cycle)}'
            + text_el(44, iy + 28, question, extra=' xml:space="preserve"')
            + f'<rect x="42" y="{iy + 8}" width="{W}" height="30" fill="{PANEL}">{discrete("x", steps_x, cycle, 42)}</rect>'
            f'<rect x="44" y="{iy + 15}" width="2" height="17" fill="{INK}">'
            f'{discrete("x", [(t, x + 1) for t, x in steps_x], cycle, 44)}</rect></g>'
        )
    box.append(
        f'<circle cx="{W - 48}" cy="{iy + 23}" r="14" fill="#3a3a3a"/>'
        f'<circle cx="{W - 48}" cy="{iy + 23}" r="14" fill="{accent}" opacity="0">{discrete("opacity", send, cycle, 0)}</circle>'
        f'<path d="M{W - 48} {iy + 30}v-13m-5 5l5-5 5 5" stroke="{BG}" stroke-width="2.2" fill="none" stroke-linecap="round"/>'
    )

    name = fit_width(name, "b", 15, 260)
    pill = fit_width(f"live · synced {synced}", "r", 12, 200)
    pill_w = width(pill, "r", 12) + 44
    header = (
        f'<rect width="{W}" height="{H}" rx="14" fill="{BG}"/>'
        f'<path d="M0 52H{W}" stroke="{LINE}"/>'
        f'<circle cx="28" cy="26" r="13" fill="{AVATAR_BG}" stroke="{AVATAR_RING}"/>'
        + spark(28, 26, 7.5, accent, '<animate attributeName="opacity" values="1;.55;1" dur="3s" repeatCount="indefinite"/>')
        + text_el(50, 31, name, "b", 15)
        + text_el(60 + width(name, "b", 15), 31, fit_width(tagline, "r", 13, W - pill_w - 110 - width(name, "b", 15)), "r", 13, FAINT)
        + f'<rect x="{W - 24 - pill_w:.1f}" y="14" width="{pill_w:.1f}" height="24" rx="12" fill="{PANEL}" stroke="{LINE}"/>'
        f'<circle cx="{W - 8 - pill_w:.1f}" cy="26" r="4" fill="#5fd38d">'
        f'<animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/></circle>'
        + text_el(W + 2 - pill_w, 30, pill, "r", 12, DIM)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(desc)}</desc>
<defs>
<style>{font_css()}</style>
<clipPath id="view"><rect x="0" y="{VIEW_TOP}" width="{W}" height="{VIEW_BOTTOM - VIEW_TOP + 10}"/></clipPath>
<linearGradient id="shimmer" gradientUnits="userSpaceOnUse" x1="0" x2="160" y1="0" y2="0">
<stop offset="0" stop-color="{FAINT}"/><stop offset=".5" stop-color="{INK}"/><stop offset="1" stop-color="{FAINT}"/>
<animateTransform attributeName="gradientTransform" type="translate" values="0 0;260 0" dur="1.6s" repeatCount="indefinite"/>
</linearGradient>
<linearGradient id="fadeTop" x2="0" y2="1"><stop stop-color="{BG}"/><stop offset="1" stop-color="{BG}" stop-opacity="0"/></linearGradient>
<linearGradient id="fadeBottom" x2="0" y2="1"><stop stop-color="{BG}" stop-opacity="0"/><stop offset="1" stop-color="{BG}"/></linearGradient>
</defs>
{header}
<g clip-path="url(#view)"><g>{scroll_anim}{history}{conversation}</g></g>
<rect x="0" y="{VIEW_TOP}" width="{W}" height="22" fill="url(#fadeTop)"/>
<rect x="0" y="{VIEW_BOTTOM - 8}" width="{W}" height="20" fill="url(#fadeBottom)"/>
{"".join(box)}
{text_el(W / 2, H - 5, fit_width(footer, "r", 10.5, W - 60), "r", 10.5, FAINT, ' text-anchor="middle"')}
</svg>
'''
