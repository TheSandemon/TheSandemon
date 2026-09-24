"""Render recent GitHub work and facts about Sand as one looping, rotating agent-chat SVG."""

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
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    kept = [line for line in body.splitlines()
            if not re.match(r"\s*(_.*_|🤖.*|https?://\S+)\s*$", line) and "claude.ai/code" not in line]
    after = [line.split(":", 1)[1].strip() for line in kept if re.match(r"\s*After:", line, re.I)]
    after = [line[:1].upper() + line[1:] for line in after]
    body = "\n".join(after + [line for line in kept if not re.match(r"\s*(Before|After):", line, re.I)])
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
            "when": commit.get("date", ""),
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


# ----------------------------------------------------------------- facts

WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


def longest_streak(days: list[dict]) -> int:
    best = run = 0
    for day in days:
        run = run + 1 if day.get("count", 0) > 0 else 0
        best = max(best, run)
    return best


def fun_facts(work: dict, lab_state: dict, lab_snapshot: dict, config: dict) -> list[str]:
    """Playful facts computed from real activity, after any hand-written ones from config."""
    facts = [clean(f) for f in config.get("fun_facts", []) if clean(f)]
    words = Counter()
    for line in [c["message"] for c in work["commits"]] + [t["title"] for t in work["tasks"]]:
        match = re.match(r"(?:\w+(?:\([^)]*\))?!?:\s*)?([A-Za-z]+)", line)
        if match:
            words[match.group(1).lower()] += 1
    if words and words.most_common(1)[0][1] >= 2:
        verb, count = words.most_common(1)[0]
        facts.append(f'Favorite first word in a commit: "{verb}" ({count} times). Very decisive.')
    stamps = []
    for commit in work["commits"]:
        try:
            stamps.append(datetime.fromisoformat(commit.get("when", "").replace("Z", "+00:00")))
        except ValueError:
            continue
    if len(stamps) >= 3:
        zone = "" if any(s.utcoffset() for s in stamps) else " (UTC)"
        day = Counter(WEEKDAYS[s.weekday()] for s in stamps).most_common(1)[0][0]
        late = round(100 * sum(s.hour >= 21 or s.hour < 5 for s in stamps) / len(stamps))
        facts.append(f"Most commits land on {day}{zone}.")
        facts.append(f"Night-owl index: {late}% of commits arrive after 9pm{zone}." if late >= 20
                     else f"Zero commits after 9pm{zone}. Suspiciously well rested." if not late
                     else f"Daylight builder: only {late}% of commits arrive after 9pm{zone}.")
    days = lab_state.get("days") or []
    if days:
        facts.append(f"Longest streak in six months: {longest_streak(days)} days in a row.")
    if lab_state.get("total_6mo"):
        facts.append(f"{lab_state['total_6mo']:,} contributions in six months; the best day hit {lab_state.get('peak_day', 0)}.")
    languages = Counter(r["language"] for r in lab_snapshot.get("repos", []) if r.get("language") and not r.get("fork"))
    if languages:
        facts.append("Speaks " + ", ".join(lang for lang, _ in languages.most_common(4)) + " (fluently-ish).")
    if lab_state.get("activity"):
        facts.append(f"Lab mood right now: {lab_state['activity'].lower()}, {str(lab_state.get('mode', 'experimenting')).lower()} mode.")
    return facts


# ---------------------------------------------------------------- scenes

def short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%b %d").upper()
    except ValueError:
        return "RECENT"


def task_ref(task: dict) -> str:
    return f"#{task['number']}" if task["number"] else task["key"].split("@")[-1]


STATE_WORDS = {"merged": "merged", "open": "in review", "draft": "drafting", "closed": "shelved", "pushed": "pushed"}


def scene_building(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    task = work["tasks"][0]
    lines = [("head", line) for line in wrap(task["title"], 84, 2)]
    lines.append(("hint", f"{task['repo']} {task_ref(task)} · {STATE_WORDS.get(task['state'], task['state'])} {short_date(task['date'])}"))
    if task["steps"]:
        lines.append(("label", "THE PLAN"))
        lines += [("body", fit(f"{i}. {step}", 98)) for i, step in enumerate(task["steps"][:3], 1)]
    files = task["files"]
    if files:
        touched = ", ".join(Path(f).name for f in files[:4]) + (f", +{len(files) - 4} more" if len(files) > 4 else "")
        lines.append(("warm", fit(f"TOUCHED {touched}", 98)))
        lines.append(("good", f"{len(files)} files · +{task['additions']} −{task['deletions']}"))
    return lines


def scene_shipped(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    commits = work["commits"][:7]
    if not commits:
        return []
    lines = [("label", "DATE   REPO              COMMIT")]
    lines += [("mono", f"{c['date'][5:]}  {fit(c['repo'], 16):<16}  {fit(c['message'], 66)}") for c in commits]
    repos = len(work["repos"])
    lines.append(("good", f"{len(work['commits'])} commits across {repos} repo{'s' if repos != 1 else ''} lately."))
    return lines


def scene_pipeline(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    task = work["tasks"][1] if len(work["tasks"]) > 1 else work["tasks"][0]
    files = task["files"]
    tests = [f for f in files if TEST_FILE.search(f)]
    active = {"draft": 1, "open": 2, "closed": 2}.get(task["state"], 3)
    stages = [("PLAN", 0), ("BUILD", 1), ("VERIFY", 2), ("SHIP", 3)]
    lines = [("head", line) for line in wrap(f"{task_ref(task)} {task['title']}", 84, 2)]
    lines.append(("stages", [(name, "done" if i < active else "active" if i == active else "todo") for name, i in stages]))
    lines.append(("body", f"plan    {fit(task['steps'][0], 90) if task['steps'] else 'straight to the keyboard'}"))
    lines.append(("body", f"build   {len(files)} files, +{task['additions']} −{task['deletions']}" if files else "build   pushed as one change"))
    names = ", ".join(Path(t).name for t in tests[:3])
    lines.append(("body", f"verify  {len(tests)} test file{'s' if len(tests) != 1 else ''}: {fit(names, 70)}"
                  if tests else "verify  eyeballs, vibes and a careful re-read"))
    lines.append(("good", f"ship    {STATE_WORDS.get(task['state'], task['state'])} in {task['repo']} {short_date(task['date'])}"))
    return lines


def scene_about(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    about = config.get("about", {})
    if not about:
        return []
    lines = [("head", fit(" · ".join(x for x in (about.get("name"), about.get("role")) if x), 84))]
    if about.get("tagline"):
        lines += [("body", line) for line in wrap(about["tagline"], 98, 2)]
    for project in about.get("projects", [])[:2]:
        lines.append(("warm", fit(f"▸ {project.get('name', '')}: {project.get('blurb', '')}", 98)))
    if about.get("links"):
        lines.append(("hint", fit("find me: " + " · ".join(about["links"]), 98)))
    if about.get("motto"):
        lines.append(("good", fit(f"“{about['motto']}”", 98)))
    return lines


def scene_fun(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    if not facts:
        return []
    return [("label", "FRESHLY COMPUTED FUN FACTS")] + [("body", fit(f"★ {fact}", 98)) for fact in facts[:7]]


def scene_quests(work: dict, facts: list[str], lab_snapshot: dict, config: dict) -> list[tuple]:
    ignored = {r.lower() for r in config.get("ignored_repos", [])} | {config["username"].lower()}
    repos = [r for r in lab_snapshot.get("repos", []) if r.get("name", "").lower() not in ignored and not r.get("archived")]
    own = [r for r in repos if not r.get("fork")][:6]
    forks = [r for r in repos if r.get("fork")][:3]
    if not own and not forks:
        return []
    lines = [("mono", f"▸ {fit(display_repo(r['name'], config), 32):<32}  {fit(r.get('language') or 'mystery', 12):<12}  {short_date(r.get('pushed_at', ''))}")
             for r in own]
    if forks:
        lines.append(("hint", fit("forked for fun: " + ", ".join(r["name"] for r in forks), 98)))
    return lines


def scene_lab(work: dict, facts: list[str], lab_snapshot: dict, config: dict, lab_state: dict | None = None) -> list[tuple]:
    state = lab_state or {}
    if not state.get("activity"):
        return []
    touched = state.get("repos_touched_7d", 0)
    machines = state.get("machines", [])
    lit = len(machines) if isinstance(machines, list) else int(machines or 0)
    return [
        ("head", f"{state['activity']} · {state.get('condition', 'STABLE')} · {state.get('mode', 'EXPERIMENTING')}"),
        ("body", f"reactor    {lit} of {state.get('machine_slots', lit)} machine bays lit, focus on {state.get('focus', 'THE LAB')}"),
        ("body", f"this week  {state.get('contributions_7d', 0)} contributions, {state.get('prs_7d', 0)} PR events, "
                 f"{touched} repo{'s' if touched != 1 else ''} touched"),
        ("body", f"today      {state.get('contributions_24h', 0)} sparks so far"),
        ("good", f"last workflow run: {state.get('workflow', 'unknown')}"),
    ]


SCENES = {
    "lab": scene_lab,
    "building": scene_building, "shipped": scene_shipped, "pipeline": scene_pipeline,
    "about": scene_about, "fun": scene_fun, "quests": scene_quests,
}


def build_scenes(work: dict, config: dict, lab_state: dict, lab_snapshot: dict) -> list[dict]:
    facts = fun_facts(work, lab_state, lab_snapshot, config)
    pipeline_task = work["tasks"][1] if len(work["tasks"]) > 1 else work["tasks"][0]
    scenes = []
    for spec in config.get("scenes", []):
        builder = SCENES.get(spec.get("id"))
        if not builder or spec.get("hidden"):
            continue
        lines = (builder(work, facts, lab_snapshot, config, lab_state) if builder is scene_lab
                 else builder(work, facts, lab_snapshot, config))
        if not lines:
            continue
        # One last guard so no line runs past the bubble, without collapsing aligned columns.
        lines = [(kind, value if kind == "stages" or len(value) <= 98 else value[:97].rstrip() + "…")
                 for kind, value in lines]
        if spec.get("quip"):
            lines.append(("hint", fit(spec["quip"], 98)))
        question = spec.get("question", spec["id"]).replace("{number}", task_ref(pipeline_task))
        scenes.append({"id": spec["id"], "topic": fit(spec.get("topic", spec["id"]), 18), "question": fit(question, 70), "lines": lines})
    if not scenes:
        raise RuntimeError("config/profile-visuals.json lists no scenes with content")
    return scenes


# ---------------------------------------------------------------- render

STYLES = {  # size, color, bold, line height
    "head": (15, INK, True, 22), "body": (13, INK, False, 21), "mono": (13, INK, False, 21),
    "hint": (12, MUTED, False, 21), "label": (11, MUTED, True, 20), "warm": (13, WARM, False, 21),
    "good": (13, LIME, True, 22), "stages": (12, INK, True, 42),
}


def text(x: float, y: float, value: str, size: int = 13, fill: str = INK, bold: bool = False, extra: str = "") -> str:
    weight = ' font-weight="bold"' if bold else ""
    return f'<text x="{x}" y="{y}" fill="{fill}" {FONT} font-size="{size}"{weight}{extra}>{escape(value)}</text>'


def rotation(index: int, count: int, cycle: float, attribute: str = "opacity") -> str:
    """A crossfade that shows item `index` for its slot of every cycle, forever."""
    if count < 2:
        return ""
    fade = min(0.6 / cycle, 0.25 / count)
    start, end = index / count, (index + 1) / count
    if index == 0:
        values, times = "1;1;0;0;1", [0, end - fade, end, 1 - fade, 1]
    elif index == count - 1:
        values, times = "0;0;1;1;0", [0, start - fade, start, 1 - fade, 1]
    else:
        values, times = "0;0;1;1;0;0", [0, start - fade, start, end - fade, end, 1]
    key_times = ";".join(f"{t:.4f}".rstrip("0").rstrip(".") if t else "0" for t in times)
    return (f'<animate attributeName="{attribute}" values="{values}" keyTimes="{key_times}" '
            f'dur="{cycle:g}s" repeatCount="indefinite"/>')


def stage_chips(x: float, y: float, stages: list[tuple[str, str]]) -> str:
    out = []
    for i, (name, status) in enumerate(stages):
        cx = x + i * 150
        color = LIME if status == "active" else ACCENT if status == "done" else DIM
        mark = "●" if status == "active" else "✓" if status == "done" else "○"
        out.append(
            (f'<path d="M{cx - 22} {y + 13}H{cx - 4}" stroke="{color}" stroke-width="3" stroke-dasharray="4 4">'
             f'<animate attributeName="stroke-dashoffset" values="8;0" dur=".8s" repeatCount="indefinite"/></path>' if i else "")
            + f'<rect x="{cx}" y="{y}" width="122" height="26" rx="13" fill="{"#275449" if status != "todo" else "#10292d"}" stroke="{color}" stroke-width="2">'
            + ('<animate attributeName="stroke-opacity" values=".3;1;.3" dur="1.6s" repeatCount="indefinite"/>' if status == "active" else "")
            + "</rect>" + text(cx + 14, y + 18, f"{mark} {name}", 12, color if status != "todo" else MUTED, True)
        )
    return "".join(out)


def render_scene(scene: dict, width: int) -> str:
    question = scene["question"]
    q_width = min(640, round(len(question) * 8.4 + 120))
    qx = width - 26 - q_width
    parts = [
        f'<rect x="{qx}" y="64" width="{q_width}" height="36" rx="10" fill="#1c4540" stroke="#4d8674" stroke-width="2"/>',
        text(qx + 14, 87, "YOU ▸", 10, MUTED, True),
        text(qx + 58, 87, question, 13, INK, True),
    ]
    height = 38 + sum(STYLES[kind][3] for kind, _ in scene["lines"])
    parts.append(
        f'<rect x="246" y="112" width="{width - 272}" height="{height}" rx="10" fill="#0c2a2f" stroke="{ACCENT}" stroke-width="2">'
        f'<animate attributeName="stroke-opacity" values=".35;1;.35" dur="3.2s" repeatCount="indefinite"/></rect>'
    )
    parts.append(text(260, 131, "◆ LAB AGENT", 10, ACCENT, True))
    y = 134
    for kind, value in scene["lines"]:
        size, color, bold, step = STYLES[kind]
        if kind == "stages":
            parts.append(stage_chips(284, y + 6, value))
        else:
            extra = ' xml:space="preserve"' if kind in {"mono", "label", "body", "good"} else ""
            parts.append(text(260, y + step - 5, value, size, color, bold, extra))
        y += step
    return "".join(parts)


def render_chat(scenes: list[dict], work: dict, config: dict, lab_state: dict) -> str:
    chat = config.get("chat", {})
    width, height = 1080, 440
    count = len(scenes)
    cycle = float(chat.get("scene_seconds", 7)) * count
    label = fit(chat.get("label", "AGENT CHAT").upper(), 30)
    subtitle = fit(chat.get("subtitle", ""), 40).upper()
    badge = fit(f"{lab_state.get('activity', 'online')} · {count} threads".upper(), 22)
    about = config.get("about", {})
    title = f"{label.title()}: {about.get('name', config['username'])}'s lab, now building {work['tasks'][0]['title']}"
    desc = " ".join(
        f"{s['question']} " + " ".join(v for kind, v in s["lines"] if kind != "stages") for s in scenes
    )
    topics = []
    for i, scene in enumerate(scenes):
        y = 104 + i * 30
        topics.append(
            f'<rect x="26" y="{y - 17}" width="196" height="25" rx="6" fill="#10292d" stroke="#1f4745" stroke-width="1"/>'
            f'<circle cx="40" cy="{y - 5}" r="3" fill="{DIM}"/>' + text(52, y, f"# {scene['topic']}", 12, MUTED)
            + f'<g opacity="{1 if i == 0 else 0}">{rotation(i, count, cycle)}'
            f'<rect x="26" y="{y - 17}" width="196" height="25" rx="6" fill="#275449" stroke="{ACCENT}" stroke-width="2"/>'
            f'<circle cx="40" cy="{y - 5}" r="4" fill="{LIME}"><animate attributeName="opacity" values="1;.3;1" dur="1.8s" repeatCount="indefinite"/></circle>'
            + text(52, y, f"# {scene['topic']}", 12, INK, True) + "</g>"
        )
    stats = [
        ("6MO SPARKS", f"{lab_state.get('total_6mo', '—')}"), ("ACTIVE DAYS", f"{lab_state.get('active_days', '—')}"),
        ("MERGED PRS", str(work["merged"])), ("REPOS", str(len(work["repos"]) or "—")),
    ]
    stat_marks = "".join(
        text(26 + (i % 2) * 100, height - 96 + (i // 2) * 42, name, 9, MUTED, True, ' letter-spacing="1"')
        + text(26 + (i % 2) * 100, height - 78 + (i // 2) * 42, value, 16, INK, True)
        for i, (name, value) in enumerate(stats)
    )
    scene_marks = "".join(
        f'<g opacity="{1 if i == 0 else 0}">{rotation(i, count, cycle)}{render_scene(scene, width)}</g>'
        for i, scene in enumerate(scenes)
    )
    dots = "".join(
        f'<circle cx="{width - 44 - (count - 1 - i) * 14}" cy="{height - 29}" r="4" fill="{DIM}"/>'
        f'<circle cx="{width - 44 - (count - 1 - i) * 14}" cy="{height - 29}" r="4" fill="{LIME}" opacity="{1 if i == 0 else 0}">{rotation(i, count, cycle)}</circle>'
        for i in range(count)
    )
    input_y = height - 44
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(fit(desc, 900))}</desc>
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
<rect x="{width - 216}" y="17" width="190" height="24" rx="12" fill="#275449" stroke="{ACCENT}" stroke-width="2"/>
<text x="{width - 121}" y="33" fill="#f0eed0" {FONT} font-size="11" font-weight="bold" text-anchor="middle">{escape(badge)}</text>
<rect x="14" y="56" width="220" height="{height - 70}" rx="10" fill="#0a2328" stroke="#1f4745" stroke-width="2"/>
{text(26, 76, "THREADS", 10, MUTED, True, ' letter-spacing="2"')}
{"".join(topics)}
<path d="M26 {height - 118}H222" stroke="#1f4745" stroke-width="1"/>
{stat_marks}
{scene_marks}
<rect x="246" y="{input_y}" width="{width - 272}" height="30" rx="8" fill="#0a2328" stroke="#2f5f58" stroke-width="2"/>
{text(260, input_y + 20, "›", 14, ACCENT, True)}
<rect x="276" y="{input_y + 8}" width="8" height="15" fill="{ACCENT}"><animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>
{text(294, input_y + 20, "ask the lab anything", 12, DIM)}
{dots}
<rect x="6" y="-40" width="{width - 12}" height="40" fill="url(#scan)"><animate attributeName="y" values="-40;{height}" dur="6s" repeatCount="indefinite"/></rect>
</svg>
'''


def readme_block(svg: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", svg, re.S)
    alt = (match.group(1) if match else "Agent chat").replace('"', "&quot;")
    return f'{README_START}\n<img src="assets/harness-chat.svg" alt="{alt}" width="100%" />\n{README_END}'


def update_readme(readme: str, block: str) -> str:
    start, end = readme.find(README_START), readme.find(README_END)
    if start == -1 or end == -1 or end < start:
        raise RuntimeError("README.md is missing the harness:start/harness:end markers")
    return readme[:start] + block + readme[end + len(README_END):]


def read_optional(path: Path) -> dict:
    """Lab pipeline outputs add flavor; the chat still renders without them."""
    try:
        return read_json(path)
    except RuntimeError as exc:
        LOG.warning("Skipping lab data: %s", exc)
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot with pulls and commits")
    parser.add_argument("--lab-state", type=Path, default=ROOT / "data" / "lab-state.json")
    parser.add_argument("--lab-snapshot", type=Path, default=ROOT / "data" / "snapshot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "harness-chat.svg")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    args = parser.parse_args()
    try:
        config = read_json(ROOT / "config" / "profile-visuals.json")
        snapshot = read_json(args.fixture) if args.fixture else fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""))
        lab_state, lab_snapshot = read_optional(args.lab_state), read_optional(args.lab_snapshot)
        work = extract_work_items(snapshot, config)
        scenes = build_scenes(work, config, lab_state, lab_snapshot)
        svg = render_chat(scenes, work, config, lab_state)
        readme = update_readme(args.readme.read_text(encoding="utf-8"), readme_block(svg))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
        args.readme.write_text(readme, encoding="utf-8")
        LOG.info("Generated %s with %s rotating scenes from %s tasks and %s commits",
                 args.output, len(scenes), len(work["tasks"]), len(work["commits"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError, re.error) as exc:
        LOG.error("Harness generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
