"""Render recent GitHub work as looping harness-style SVG panels below Sandemon's Lab."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_lab import ROOT, read_json, request_json  # noqa: E402


LOG = logging.getLogger("sandemon.harness")
API = "https://api.github.com"
README_START = "<!-- harness:start -->"
README_END = "<!-- harness:end -->"
PANEL_TYPES = {"chat", "terminal", "flow"}
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|[._-](test|spec)\.[^/]+$")
FONT = 'font-family="monospace"'
INK = "#f3ebc7"
MUTED = "#86bea9"
DIM = "#4d8674"
ACCENT = "#8be5bd"
LIME = "#bdf798"
WARM = "#ffd690"


# ---------------------------------------------------------------- fetch

def fetch_snapshot(config: dict, token: str) -> dict:
    """Collect public PRs and commits authored by the user, plus files for the newest PRs."""
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to search recent work")
    user = config["username"]
    visibility = "" if config.get("include_private") else "+is:public"
    pulls, commits = [], []
    try:
        found = request_json(
            f"{API}/search/issues?q=author:{quote(user)}+type:pr{visibility}"
            f"&sort=updated&order=desc&per_page={int(config.get('max_pulls', 20))}",
            token,
        )
        for item in found.get("items", []) if isinstance(found, dict) else []:
            repo = item["repository_url"].split("/repos/", 1)[-1]
            pulls.append({
                "repo": repo,
                "number": item["number"],
                "title": item["title"],
                "body": item.get("body") or "",
                "state": "draft" if item.get("draft") else item["state"],
                "merged_at": (item.get("pull_request") or {}).get("merged_at"),
                "updated_at": item["updated_at"],
                "url": item["html_url"],
            })
    except (RuntimeError, KeyError, TypeError, AttributeError) as exc:
        LOG.warning("Pull request search unavailable: %s", exc)
    try:
        found = request_json(
            f"{API}/search/commits?q=author:{quote(user)}{visibility}"
            f"&sort=author-date&order=desc&per_page={int(config.get('max_commits', 30))}",
            token,
        )
        for item in found.get("items", []) if isinstance(found, dict) else []:
            repository = item.get("repository") or {}
            commits.append({
                "repo": repository["full_name"],
                "private": bool(repository.get("private")),
                "sha": item["sha"],
                "message": item["commit"]["message"],
                "date": item["commit"]["author"]["date"],
                "url": item["html_url"],
            })
    except (RuntimeError, KeyError, TypeError, AttributeError) as exc:
        LOG.warning("Commit search unavailable: %s", exc)
    if not pulls and not commits:
        raise RuntimeError("GitHub returned no pull requests or commits to trace")

    # File lists cost one request per PR, so only fetch them for the items that may be featured.
    wanted = set(config.get("featured", []))
    candidates = [p for p in pulls if f"{p['repo']}#{p['number']}" in wanted] + pulls[:2]
    for pull in candidates:
        if "files" in pull:
            continue
        try:
            files = request_json(f"{API}/repos/{pull['repo']}/pulls/{pull['number']}/files?per_page=100", token)
            pull["files"] = [
                {"name": f["filename"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
                for f in files
            ] if isinstance(files, list) else []
        except (RuntimeError, KeyError, TypeError) as exc:
            LOG.warning("Files unavailable for %s#%s: %s", pull["repo"], pull["number"], exc)
    return {"pulls": pulls, "commits": commits}


# -------------------------------------------------------------- extract

def clean(text: str) -> str:
    """Strip markdown noise and control characters from one line of GitHub text."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`|\*\*", "", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fit(text: str, width: int) -> str:
    text = clean(text)
    return text if len(text) <= width else text[: max(1, width - 1)].rstrip() + "…"


def wrap(text: str, width: int, lines: int) -> list[str]:
    out, line = [], ""
    for word in clean(text).split():
        candidate = f"{line} {word}".strip()
        if len(candidate) <= width or not line:
            line = candidate
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: width - 1].rstrip() + "…"
    return [fit(item, width) for item in out]


def plan_steps(body: str, limit: int = 3) -> list[str]:
    """Pull short steps from a PR description: bullet lines first, else the first sentences."""
    steps = []
    for raw in body.splitlines():
        match = re.match(r"\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+)", raw)
        if match and clean(match.group(1)):
            steps.append(clean(match.group(1)))
        if len(steps) == limit:
            return steps
    if steps:
        return steps
    prose = " ".join(clean(line) for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    return [s for s in re.split(r"(?<=[.!?])\s+", prose) if s][:limit]


def display_repo(repo: str, config: dict) -> str:
    owner, _, name = repo.partition("/")
    aliases = config.get("repo_aliases", {})
    if repo in aliases or name in aliases:
        return aliases.get(repo, aliases.get(name))
    return name if owner.lower() == config["username"].lower() else repo


def extract_work_items(snapshot: dict, config: dict) -> dict:
    """Turn raw PRs and commits into ranked, cleaned work items for the panels."""
    ignored_repos = {r.lower() for r in config.get("ignored_repos", [])}
    patterns = [re.compile(p, re.IGNORECASE) for p in config.get("ignored_patterns", [])]
    summaries = config.get("summaries", {})

    def skip(repo: str, text: str) -> bool:
        name = repo.split("/")[-1].lower()
        return repo.lower() in ignored_repos or name in ignored_repos or any(p.search(text) for p in patterns)

    tasks = []
    for pull in snapshot.get("pulls", []):
        title = clean(pull.get("title", ""))
        if not title or skip(pull["repo"], title):
            continue
        key = f"{pull['repo'].split('/')[-1]}#{pull['number']}"
        full_key = f"{pull['repo']}#{pull['number']}"
        override = summaries.get(full_key, summaries.get(key))
        steps = [clean(s) for s in ([override] if isinstance(override, str) else override or [])] or plan_steps(pull.get("body", ""))
        files = pull.get("files", [])
        state = "merged" if pull.get("merged_at") else pull.get("state", "open")
        tasks.append({
            "key": full_key,
            "kind": "pr",
            "repo": display_repo(pull["repo"], config),
            "number": pull["number"],
            "title": title,
            "steps": steps,
            "files": [f["name"] for f in files],
            "additions": sum(f.get("additions", 0) for f in files),
            "deletions": sum(f.get("deletions", 0) for f in files),
            "tests": sum(bool(TEST_FILE.search(f["name"])) for f in files),
            "state": state,
            "date": (pull.get("merged_at") or pull.get("updated_at") or "")[:10],
        })

    commits = []
    for commit in snapshot.get("commits", []):
        if commit.get("private") and not config.get("include_private"):
            continue
        message = clean(commit.get("message", "").splitlines()[0] if commit.get("message") else "")
        if not message or skip(commit["repo"], message):
            continue
        commits.append({
            "repo": display_repo(commit["repo"], config),
            "sha": commit["sha"][:7],
            "message": message,
            "date": commit.get("date", "")[:10],
        })
    commits.sort(key=lambda c: c["date"], reverse=True)

    featured = config.get("featured", [])
    rank = {key: index for index, key in enumerate(featured)}
    tasks.sort(key=lambda t: t["date"], reverse=True)
    tasks.sort(key=lambda t: rank.get(t["key"], rank.get(t["key"].split("/")[-1], len(rank))))
    if not tasks and commits:
        # With no PRs, the newest commit still makes a readable task.
        head = commits[0]
        tasks.append({
            "key": f"{head['repo']}@{head['sha']}", "kind": "commit", "repo": head["repo"], "number": None,
            "title": head["message"], "steps": [], "files": [], "additions": 0, "deletions": 0,
            "tests": 0, "state": "pushed", "date": head["date"],
        })
    if not tasks:
        raise RuntimeError("Every recent work item was ignored; nothing to render")
    repos = Counter(c["repo"] for c in commits)
    return {
        "tasks": tasks,
        "commits": commits,
        "repos": repos.most_common(),
        "merged": sum(t["state"] == "merged" for t in tasks),
    }


# ---------------------------------------------------------------- render

def short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%b %d").upper()
    except ValueError:
        return "RECENT"


def text(x: float, y: float, value: str, size: int = 13, fill: str = INK, bold: bool = False, extra: str = "") -> str:
    weight = ' font-weight="bold"' if bold else ""
    return f'<text x="{x}" y="{y}" fill="{fill}" {FONT} font-size="{size}"{weight}{extra}>{escape(value)}</text>'


def frame(width: int, height: int, panel: dict, badge: str, title: str, desc: str) -> tuple[str, str]:
    label = fit(panel.get("label", panel["type"]).upper(), 34)
    subtitle = fit(panel.get("subtitle", ""), 40).upper()
    head = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(desc)}</desc>
<defs>
  <linearGradient id="bg" x2="0" y2="1"><stop stop-color="#11292e"/><stop offset="1" stop-color="#071a21"/></linearGradient>
  <linearGradient id="scan" x2="0" y2="1"><stop stop-color="#d9ffb5" stop-opacity="0"/><stop offset=".5" stop-color="#d9ffb5" stop-opacity=".06"/><stop offset="1" stop-color="#d9ffb5" stop-opacity="0"/></linearGradient>
</defs>
<rect width="{width}" height="{height}" rx="16" fill="url(#bg)"/>
<rect x="2" y="2" width="{width - 4}" height="{height - 4}" rx="15" fill="none" stroke="#588878" stroke-width="3"/>
<rect x="14" y="12" width="{width - 28}" height="34" rx="9" fill="#163a3a" stroke="#4c8371" stroke-width="2"/>
<circle cx="34" cy="29" r="5" fill="#ff927b"/><circle cx="51" cy="29" r="5" fill="{WARM}"/>
<circle cx="68" cy="29" r="5" fill="{ACCENT}"><animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>
{text(88, 34, label, 14, INK, True, ' letter-spacing="2"')}
{text(112 + len(label) * 10.4, 34, subtitle, 11, MUTED, False, ' letter-spacing="1"')}
<rect x="{width - 186}" y="17" width="160" height="24" rx="12" fill="#275449" stroke="{ACCENT}" stroke-width="2"/>
<text x="{width - 106}" y="33" fill="#f0eed0" {FONT} font-size="11" font-weight="bold" text-anchor="middle">{escape(fit(badge.upper(), 22))}</text>
'''
    tail = f'''<rect x="6" y="-40" width="{width - 12}" height="40" fill="url(#scan)"><animate attributeName="y" values="-40;{height}" dur="6s" repeatCount="indefinite"/></rect>
</svg>
'''
    return head, tail


def render_chat(work: dict, panel: dict) -> str:
    task = work["tasks"][0]
    width, height = 1080, 330
    ref = f"#{task['number']}" if task["number"] else task["key"].split("@")[-1]
    head, tail = frame(width, height, panel, f"{task['state']} · {short_date(task['date'])}",
                       f"{panel.get('label', 'Agent chat')}: {task['title']}",
                       f"A chat-style harness panel. Task: {task['title']} in {task['repo']}. "
                       f"Plan: {'; '.join(task['steps']) or 'none recorded'}.")
    sessions = []
    names = [task["repo"]] + [repo for repo, _ in work["repos"] if repo != task["repo"]]
    for index, name in enumerate(names[:5]):
        y = 104 + index * 30
        active = index == 0
        sessions.append(
            f'<rect x="26" y="{y - 17}" width="196" height="25" rx="6" fill="{"#275449" if active else "#10292d"}"'
            f' stroke="{ACCENT if active else "#1f4745"}" stroke-width="{2 if active else 1}"/>'
            + (f'<circle cx="40" cy="{y - 5}" r="4" fill="{LIME}"><animate attributeName="opacity" values="1;.3;1" dur="1.8s" repeatCount="indefinite"/></circle>'
               if active else f'<circle cx="40" cy="{y - 5}" r="3" fill="{DIM}"/>')
            + text(52, y, fit(name, 20), 12, INK if active else MUTED, active)
        )
    title_lines = wrap(task["title"], 78, 2)
    steps = task["steps"][:3] or ["Shipped straight from the terminal."]
    files = task["files"]
    touched = ", ".join(Path(f).name for f in files[:4]) + (f", +{len(files) - 4} more" if len(files) > 4 else "")
    result = {
        "merged": f"Merged into {task['repo']} {ref}",
        "open": f"In review on {task['repo']} {ref}",
        "draft": f"Drafting on {task['repo']} {ref}",
        "closed": f"Shelved on {task['repo']} {ref}",
        "pushed": f"Pushed to {task['repo']} @ {ref}",
    }.get(task["state"], f"{task['state']} on {task['repo']}")
    if files:
        result += f" · {len(files)} files · +{task['additions']} −{task['deletions']}"
    user_h = 28 + 18 * len(title_lines)
    agent_y = 72 + user_h + 12
    agent_lines = [("PLAN", MUTED, True)] + [(f"{i}. {fit(s, 96)}", INK, False) for i, s in enumerate(steps, 1)]
    if touched:
        agent_lines.append((fit(f"FILES  {touched}", 100), WARM, False))
    agent_lines.append((fit(f"RESULT {result}", 100), LIME, True))
    agent_h = 30 + 19 * len(agent_lines)
    bubble = [
        f'<rect x="{width - 26 - 640}" y="68" width="640" height="{user_h}" rx="10" fill="#1c4540" stroke="#4d8674" stroke-width="2"/>',
        text(width - 26 - 626, 86, "YOU ▸ TASK", 10, MUTED, True),
    ] + [text(width - 26 - 626, 104 + i * 18, line, 13, INK, True) for i, line in enumerate(title_lines)]
    bubble += [
        f'<rect x="246" y="{agent_y}" width="{width - 272}" height="{agent_h}" rx="10" fill="#0c2a2f" stroke="{ACCENT}" stroke-width="2">'
        f'<animate attributeName="stroke-opacity" values=".35;1;.35" dur="3.2s" repeatCount="indefinite"/></rect>',
        text(260, agent_y + 18, "◆ AGENT", 10, ACCENT, True),
    ]
    for i, (line, color, bold) in enumerate(agent_lines):
        bubble.append(text(260, agent_y + 38 + i * 19, line, 12 if not bold else 11, color, bold))
    input_y = height - 44
    return head + f'''<rect x="14" y="56" width="220" height="{height - 70}" rx="10" fill="#0a2328" stroke="#1f4745" stroke-width="2"/>
{text(26, 76, "SESSIONS", 10, MUTED, True, ' letter-spacing="2"')}
{"".join(sessions)}
{text(26, height - 26, f"{work['merged']} MERGED · {len(work['tasks'])} TASKS", 10, MUTED, True)}
{"".join(bubble)}
<rect x="246" y="{input_y}" width="{width - 272}" height="30" rx="8" fill="#0a2328" stroke="#2f5f58" stroke-width="2"/>
{text(260, input_y + 20, "›", 14, ACCENT, True)}
<rect x="276" y="{input_y + 8}" width="8" height="15" fill="{ACCENT}"><animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>
<g fill="{MUTED}">
  <circle cx="{width - 70}" cy="{input_y + 15}" r="3"><animate attributeName="opacity" values=".2;1;.2" dur="1.4s" repeatCount="indefinite"/></circle>
  <circle cx="{width - 58}" cy="{input_y + 15}" r="3"><animate attributeName="opacity" values=".2;1;.2" dur="1.4s" begin=".2s" repeatCount="indefinite"/></circle>
  <circle cx="{width - 46}" cy="{input_y + 15}" r="3"><animate attributeName="opacity" values=".2;1;.2" dur="1.4s" begin=".4s" repeatCount="indefinite"/></circle>
</g>
''' + tail


def render_terminal(work: dict, panel: dict, username: str) -> str:
    width, height = 1080, 300
    commits = work["commits"][:10]
    repos = work["repos"][:5]
    head, tail = frame(width, height, panel, f"{len(work['commits'])} commits · {len(work['repos'])} repos",
                       f"{panel.get('label', 'Terminal')}: recent commits",
                       "A terminal-style harness panel scrolling recent commits: "
                       + "; ".join(f"{c['repo']}: {c['message']}" for c in commits[:5]))
    rows = []
    source = commits or [{"date": t["date"], "repo": t["repo"], "sha": "·······", "message": t["title"]} for t in work["tasks"][:6]]
    for i, commit in enumerate(source):
        y = i * 22
        rows.append(
            text(0, y, commit["date"][5:] or "--", 12, DIM)
            + text(52, y, fit(commit["repo"], 16), 12, WARM)
            + text(186, y, commit["sha"], 12, MUTED)
            + text(254, y, fit(commit["message"], 56), 12, INK)
        )
    view_h = 138
    block_h = len(rows) * 22
    body = "".join(rows)
    if block_h > view_h:
        scroller = (f'<g><animateTransform attributeName="transform" type="translate" from="0 0" to="0 -{block_h}"'
                    f' dur="{len(rows) * 2.6:.1f}s" repeatCount="indefinite"/>{body}'
                    f'<g transform="translate(0 {block_h})">{body}</g></g>')
    else:
        scroller = body
    peak = max((n for _, n in repos), default=1)
    meters = []
    for i, (repo, count) in enumerate(repos):
        y = 104 + i * 34
        bar = max(8, round(280 * count / peak))
        meters.append(
            text(760, y, fit(repo, 18), 11, INK, True) + text(1040, y, str(count), 11, MUTED, False, ' text-anchor="end"')
            + f'<rect x="760" y="{y + 7}" width="280" height="8" rx="4" fill="#10292d"/>'
            + f'<rect x="760" y="{y + 7}" width="{bar}" height="8" rx="4" fill="{ACCENT}">'
            f'<animate attributeName="opacity" values=".55;1;.55" dur="{2 + i * .4:.1f}s" repeatCount="indefinite"/></rect>'
        )
    if not meters:
        meters.append(text(760, 110, "no commit stream yet", 11, MUTED))
    prompt = fit(f"$ orchestrate --trace --author {username}", 60)
    return head + f'''<rect x="14" y="56" width="720" height="{height - 70}" rx="10" fill="#061519" stroke="#1f4745" stroke-width="2"/>
{text(30, 80, prompt, 13, LIME, True)}
{text(30, 98, "DATE", 10, DIM, True)}{text(82, 98, "REPO", 10, DIM, True)}{text(216, 98, "SHA", 10, DIM, True)}{text(284, 98, "MESSAGE", 10, DIM, True)}
<clipPath id="logClip"><rect x="0" y="-14" width="690" height="{view_h}"/></clipPath>
<g transform="translate(30 122)" clip-path="url(#logClip)">{scroller}</g>
<path d="M28 {height - 42}H718" stroke="#1f4745" stroke-width="1"/>
{text(30, height - 24, "›", 14, ACCENT, True)}
<rect x="46" y="{height - 36}" width="8" height="15" fill="{ACCENT}"><animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>
<rect x="746" y="56" width="{width - 760}" height="{height - 70}" rx="10" fill="#0a2328" stroke="#1f4745" stroke-width="2"/>
{text(760, 80, "WORKERS / COMMITS", 10, MUTED, True, ' letter-spacing="2"')}
{"".join(meters)}
''' + tail


def render_flow(work: dict, panel: dict) -> str:
    task = work["tasks"][1] if len(work["tasks"]) > 1 and work["tasks"][1]["files"] else work["tasks"][0]
    width, height = 1080, 280
    files = task["files"]
    code = [f for f in files if not TEST_FILE.search(f)]
    tests = [f for f in files if TEST_FILE.search(f)]
    stages = [
        ("PLAN", f"{len(task['steps'])} steps" if task["steps"] else "direct push",
         wrap(task["steps"][0] if task["steps"] else task["title"], 27, 3)),
        ("BUILD", f"{len(files)} files +{task['additions']} −{task['deletions']}" if files else "change pushed",
         [fit(Path(f).name, 27) for f in code[:3]] or ["files not listed"]),
        ("VERIFY", f"{len(tests)} test file{'s' if len(tests) != 1 else ''}" if tests else "no test files",
         [fit(Path(f).name, 27) for f in tests[:3]] or ["reviewed by hand"]),
        ("SHIP", {"merged": "merged", "open": "in review", "draft": "draft", "closed": "shelved",
                  "pushed": "pushed"}.get(task["state"], task["state"]),
         [fit(task["repo"], 27), short_date(task["date"])]),
    ]
    active = {"draft": 1, "open": 2, "closed": 2}.get(task["state"], 3)
    head, tail = frame(width, height, panel, f"{task['repo']}",
                       f"{panel.get('label', 'Pipeline')}: {task['title']}",
                       f"A plan, build, verify, ship pipeline for {task['title']}: "
                       + "; ".join(f"{name} {summary}" for name, summary, _ in stages))
    nodes, links = [], []
    for i, (name, summary, details) in enumerate(stages):
        x = 26 + i * 262
        done, current = i < active, i == active
        stroke = LIME if current else ACCENT if done else "#2f5f58"
        glow = (f'<rect x="{x - 4}" y="96" width="230" height="130" rx="14" fill="none" stroke="{LIME}" stroke-width="6">'
                f'<animate attributeName="opacity" values=".08;.4;.08" dur="2.2s" repeatCount="indefinite"/></rect>') if current else ""
        nodes.append(
            glow
            + f'<rect x="{x}" y="100" width="222" height="122" rx="10" fill="{"#173d3c" if done or current else "#0c2429"}" stroke="{stroke}" stroke-width="2"/>'
            + f'<circle cx="{x + 18}" cy="120" r="6" fill="{stroke}"/>'
            + text(x + 32, 125, name, 13, INK if done or current else MUTED, True, ' letter-spacing="2"')
            + text(x + 14, 150, fit(summary, 28), 12, LIME if current else WARM, True)
            + "".join(text(x + 14, 172 + j * 18, line, 12, INK if done or current else MUTED) for j, line in enumerate(details[:3]))
        )
        if i < 3:
            lit = i < active
            links.append(
                f'<path d="M{x + 222} 161H{x + 262}" stroke="{ACCENT if lit else "#2f5f58"}" stroke-width="4" stroke-dasharray="6 6">'
                f'<animate attributeName="stroke-dashoffset" values="12;0" dur="{.6 if lit else 1.6}s" repeatCount="indefinite"/></path>'
            )
    ref = f"#{task['number']} · " if task["number"] else ""
    return head + f'''{text(26, 76, fit(f"{ref}{task['title']}", 118), 13, INK, True)}
{"".join(links)}
{"".join(nodes)}
<rect x="26" y="{height - 34}" width="{width - 52}" height="8" rx="4" fill="#10292d"/>
<rect x="26" y="{height - 34}" width="{round((width - 52) * (active + 1) / 4)}" height="8" rx="4" fill="{ACCENT}" opacity=".7"/>
<rect x="26" y="{height - 34}" width="60" height="8" rx="4" fill="{LIME}" opacity=".8">
  <animate attributeName="x" values="26;{26 + round((width - 52) * (active + 1) / 4) - 60};26" dur="4s" repeatCount="indefinite"/>
</rect>
''' + tail


def render_panels(work: dict, config: dict) -> list[tuple[dict, str]]:
    panels = []
    for panel in config.get("panels", []):
        kind = panel.get("type")
        if kind not in PANEL_TYPES or panel.get("hidden"):
            continue
        if not re.fullmatch(r"[a-z0-9-]+", str(panel.get("id", ""))):
            raise RuntimeError(f"Panel id must be lowercase letters, digits or dashes: {panel.get('id')!r}")
        if kind == "chat":
            svg = render_chat(work, panel)
        elif kind == "terminal":
            svg = render_terminal(work, panel, config["username"])
        else:
            svg = render_flow(work, panel)
        panels.append((panel, svg))
    if not panels:
        raise RuntimeError("config/profile-visuals.json lists no renderable panels")
    return panels


def readme_block(panels: list[tuple[dict, str]]) -> str:
    lines = [README_START]
    for panel, svg in panels:
        match = re.search(r"<title[^>]*>(.*?)</title>", svg, re.S)
        alt = (match.group(1) if match else panel["id"]).replace('"', "&quot;")
        lines.append(f'<img src="assets/harness-{panel["id"]}.svg" alt="{alt}" width="100%" />')
    lines.append(README_END)
    return "\n".join(lines)


def update_readme(readme: str, block: str) -> str:
    start, end = readme.find(README_START), readme.find(README_END)
    if start == -1 or end == -1 or end < start:
        raise RuntimeError("README.md is missing the harness:start/harness:end markers")
    return readme[:start] + block + readme[end + len(README_END):]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot with pulls and commits")
    parser.add_argument("--assets", type=Path, default=ROOT / "assets")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = parser.parse_args()
    try:
        config = read_json(ROOT / "config" / "profile-visuals.json")
        snapshot = read_json(args.fixture) if args.fixture else fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""))
        work = extract_work_items(snapshot, config)
        panels = render_panels(work, config)
        readme = update_readme(args.readme.read_text(encoding="utf-8"), readme_block(panels))
        args.assets.mkdir(parents=True, exist_ok=True)
        for panel, svg in panels:
            (args.assets / f"harness-{panel['id']}.svg").write_text(svg, encoding="utf-8")
        args.readme.write_text(readme, encoding="utf-8")
        LOG.info("Generated %s harness panels from %s tasks and %s commits",
                 len(panels), len(work["tasks"]), len(work["commits"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError, re.error) as exc:
        LOG.error("Harness generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
