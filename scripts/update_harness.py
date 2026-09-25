"""Turn recent public GitHub work and facts about Sand into one endlessly typing agent-chat SVG."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import logging
import os
from pathlib import Path
import random
import re
import sys
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_lab import ROOT, read_json, request_json  # noqa: E402
import chat_svg  # noqa: E402


LOG = logging.getLogger("sandemon.harness")
API = "https://api.github.com"
README_START = "<!-- harness:start -->"
README_END = "<!-- harness:end -->"
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|[._-](test|spec)\.[^/]+$")


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
    return facts




# ----------------------------------------------------------- conversation

def md(text: str) -> list[tuple[str, str]]:
    """Split **bold** and `code` spans out of one line of copy into styled segments."""
    segments = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            segments.append((part[2:-2], "b"))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            segments.append((part[1:-1], "m"))
        elif part:
            segments.append((part, "r"))
    return segments


def short_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso[:10]).strftime("%b %d").replace(" 0", " ")
    except ValueError:
        return "recently"


def task_ref(task: dict) -> str:
    return f"#{task['number']}" if task["number"] else task["key"].split("@")[-1]


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


STATE_WORDS = {"merged": "merged", "open": "in review", "draft": "a draft", "closed": "shelved", "pushed": "pushed"}


def beat_intro(ctx: dict, spec: dict) -> list[dict]:
    about = ctx["config"].get("about", {})
    if not about.get("name"):
        return []
    lead = f"**{about['name']}**, better known around here as Sand."
    if about.get("role"):
        lead += f" {about['role']}."
    if about.get("tagline"):
        lead += f" {about['tagline']}"
    paragraphs = [md(lead)]
    projects = about.get("projects", [])
    if projects:
        paragraphs.append(md(f"The headline act is **{projects[0]['name']}**: {projects[0].get('blurb', '')}"))
    return [{"steps": [("think", 1.6), ("say", paragraphs)]}]


def beat_day_job(ctx: dict, spec: dict) -> list[dict]:
    roles = ctx["config"].get("about", {}).get("career", [])
    if not roles:
        return []
    now = roles[0]
    lead = f"By day, Sand is **{now['title']}** at **{now['org']}**"
    lead += f", {now['note']}." if now.get("note") else "."
    paragraphs = [md(lead)]
    for role in roles[1:3]:
        paragraphs.append(md(f"Earlier: **{role['title']}** at **{role['org']}**."))
    if ctx["config"].get("about", {}).get("after_hours"):
        paragraphs.append(md(ctx["config"]["about"]["after_hours"]))
    source = ctx["config"].get("about", {}).get("career_source", "the resume")
    return [{"steps": [("tool", f"Reading {source}", f"Read {source}"), ("think", 0.9), ("say", paragraphs)]}]


def beat_building(ctx: dict, spec: dict) -> list[dict]:
    work = ctx["work"]
    task = work["tasks"][0]
    repos = len(work["repos"])
    steps = [("tool", "Searching GitHub", f"Searched GitHub · {plural(len(work['commits']), 'recent commit')} across {plural(repos, 'repo')}"),
             ("think", 1.2)]
    state = STATE_WORDS.get(task["state"], task["state"])
    steps.append(("say", [md(f"Latest: **{task['title']}** in {task['repo']} ({task_ref(task)}, {state}, {short_date(task['date'])}).")]))
    if task["steps"]:
        steps.append(("say", [md("The plan, straight from the PR:")]))
        steps.append(("bullets", [md(fit(step, 160)) for step in task["steps"][:3]]))
    if task["files"]:
        names = ", ".join(f"`{Path(f).name}`" for f in task["files"][:3])
        more = f" and {len(task['files']) - 3} more" if len(task["files"]) > 3 else ""
        tests = f", {plural(task['tests'], 'test file')} included" if task["tests"] else ""
        steps.append(("say", [md(f"{plural(len(task['files']), 'file')} touched (+{task['additions']} / -{task['deletions']}){tests}: {names}{more}.")]))
    return [{"steps": steps}]


def beat_shipped(ctx: dict, spec: dict) -> list[dict]:
    commits = ctx["work"]["commits"][:6]
    if not commits:
        return []
    rows = [(short_date(c["date"]), fit(c["repo"], 20), re.sub(r"\s*\(#\d+\)$", "", c["message"])) for c in commits]
    header = f"git log --author={ctx['config']['username']} --public"
    days = len({c["date"] for c in ctx["work"]["commits"]})
    return [{"steps": [
        ("think", 1.0),
        ("say", [md("Here's the latest public work:")]),
        ("code", header, rows),
        ("say", [md(f"{plural(len(ctx['work']['commits']), 'commit')} on {plural(days, 'different day')} in the recent log.")]),
    ]}]


def workbench_repos(ctx: dict, skip: list[str] = ()) -> list[dict]:
    config = ctx["config"]
    ignored = {r.lower() for r in [*config.get("ignored_repos", []), *skip]} | {config["username"].lower()}
    return [r for r in ctx["lab_snapshot"].get("repos", [])
            if r.get("name", "").lower() not in ignored and not r.get("fork") and not r.get("archived")
            and not r.get("private")]


def beat_workbench(ctx: dict, spec: dict) -> list[dict]:
    repos = workbench_repos(ctx, spec.get("skip", []))[: int(spec.get("max_repos", 6))]
    questions = spec.get("questions") or ["what else is on the workbench?"]
    beats = []
    for index in range(0, len(repos), 2):
        paragraphs = []
        for repo in repos[index:index + 2]:
            name = display_repo(repo["name"], ctx["config"])
            facts = [repo.get("language")] + ([plural(repo["stars"], "star")] if repo.get("stars") else [])
            detail = f" ({', '.join(f for f in facts if f)})" if any(facts) else ""
            about = clean(repo.get("description") or "") or f"last pushed {short_date(repo.get('pushed_at') or '')}."
            paragraphs.append(md(f"**{name}**{detail}: {fit(about, 240)}"))
        question = questions[len(beats) % len(questions)]
        beats.append({"question": question, "steps": [("think", 1.1), ("say", paragraphs)]})
    return beats


def beat_stats(ctx: dict, spec: dict) -> list[dict]:
    lab = ctx["lab_state"]
    if not lab.get("total_6mo"):
        return []
    days = lab.get("days") or []
    cells = [(f"{lab['total_6mo']:,}", "contributions, 6 mo"), (str(lab.get("active_days", 0)), "active days"),
             (str(longest_streak(days)), "days, best streak"), (str(lab.get("peak_day", 0)), "on the busiest day")]
    steps = [("tool", "Reading the contribution calendar", f"Read {plural(len(days), 'day')} of contributions"),
             ("think", 1.0), ("stats", cells)]
    if lab.get("contributions_7d"):
        steps.append(("say", [md(f"This week so far: {plural(lab['contributions_7d'], 'contribution')} and {plural(lab.get('prs_7d', 0), 'pull request event')}.")]))
    return [{"steps": steps}]


def beat_habits(ctx: dict, spec: dict) -> list[dict]:
    facts = fun_facts(ctx["work"], ctx["lab_state"], ctx["lab_snapshot"], {**ctx["config"], "fun_facts": []})
    facts = [f for f in facts if not f.startswith(("Longest streak", f"{ctx['lab_state'].get('total_6mo', 0):,} contributions"))]
    if not facts:
        return []
    return [{"steps": [("think", 1.4), ("say", [md("Computed from the actual commit log:")]),
                       ("bullets", [md(f) for f in facts[:4]])]}]


def beat_fun(ctx: dict, spec: dict) -> list[dict]:
    facts = [clean(f) for f in ctx["config"].get("fun_facts", []) if clean(f)]
    questions = spec.get("questions") or ["tell me something fun about Sand"]
    size = int(spec.get("per_answer", 3))
    beats = []
    for index in range(0, len(facts), size):
        beats.append({"question": questions[len(beats) % len(questions)],
                      "steps": [("think", 1.3), ("bullets", [md(f) for f in facts[index:index + size]])]})
    return beats


def beat_qa(ctx: dict, spec: dict) -> list[dict]:
    """A hand-written answer from config: optional tool row, paragraphs, bullets, stat tiles, a card and an outro."""
    steps = []
    if spec.get("tool"):
        steps.append(("tool", spec["tool"][0], spec["tool"][1]))
    steps.append(("think", float(spec.get("think", 1.2))))
    if spec.get("say"):
        steps.append(("say", [md(text) for text in spec["say"]]))
    if spec.get("tiles"):
        steps.append(("stats", [(str(number), label) for number, label in spec["tiles"][:4]]))
    if spec.get("bullets"):
        steps.append(("bullets", [md(text) for text in spec["bullets"]]))
    if spec.get("card"):
        rows = [tuple(str(cell) for cell in row[:3]) for row in spec["card"].get("rows", [])]
        steps.append(("code", spec["card"].get("header", ""), rows))
    if spec.get("outro"):
        steps.append(("say", [md(text) for text in spec["outro"]]))
    return [{"steps": steps}] if len(steps) > 1 else []


def beat_contact(ctx: dict, spec: dict) -> list[dict]:
    about = ctx["config"].get("about", {})
    links = about.get("links", [])
    if not links:
        return []
    paragraphs = [md("Find Sand at " + ", ".join(f"**{link}**" for link in links[:-1]) + (" or " if len(links) > 1 else "") + f"**{links[-1]}**.")]
    if about.get("motto"):
        paragraphs.append(md(f"Sand's motto, verbatim: **{about['motto']}**"))
    return [{"steps": [("think", 0.9), ("say", paragraphs)]}]


BEATS = {
    "intro": beat_intro, "day-job": beat_day_job, "building": beat_building, "shipped": beat_shipped,
    "workbench": beat_workbench, "stats": beat_stats, "habits": beat_habits, "fun": beat_fun, "contact": beat_contact,
    "qa": beat_qa,
}


def build_conversation(work: dict, config: dict, lab_state: dict, lab_snapshot: dict, today: date) -> list[tuple]:
    """Expand the configured beats into steps.

    The first and last beats, and any beat marked "pinned", keep their places; the rest trade places daily.
    A beat's "type" picks its builder (defaulting to its id), so several "qa" beats can share one builder.
    """
    ctx = {"work": work, "config": config, "lab_state": lab_state, "lab_snapshot": lab_snapshot}
    groups, pinned = [], []
    for spec in config.get("beats", []):
        builder = BEATS.get(spec.get("type", spec.get("id")))
        if not builder or spec.get("hidden"):
            continue
        beats = builder(ctx, spec)
        if beats:
            groups.append([dict(b, question=b.get("question") or spec.get("question") or spec["id"]) for b in beats])
            pinned.append(bool(spec.get("pinned")))
    if not groups:
        raise RuntimeError("config/profile-visuals.json lists no beats with content")
    if config.get("chat", {}).get("shuffle", True) and len(groups) > 3:
        pinned[0] = pinned[-1] = True
        slots = [i for i, fixed in enumerate(pinned) if not fixed]
        loose = [groups[i] for i in slots]
        random.Random(today.isoformat()).shuffle(loose)
        for i, group in zip(slots, loose):
            groups[i] = group
    steps = []
    for beat in (beat for group in groups for beat in group):
        steps.append(("user", beat["question"]))
        steps.extend(beat["steps"])
    return steps


def transcript(steps: list[tuple], limit: int = 1500) -> str:
    """Plain-text version of the conversation for screen readers."""
    parts = []
    for step in steps:
        if step[0] == "user":
            parts.append(f"Q: {step[1]}")
        elif step[0] in ("say", "bullets"):
            parts.extend("".join(text for text, _ in segments) for segments in step[1])
        elif step[0] == "code":
            parts.extend(" ".join(row) for row in step[2])
        elif step[0] == "stats":
            parts.append(", ".join(f"{n} {label}" for n, label in step[1]))
    return fit(" ".join(parts), limit)


def render_chat(steps: list[tuple], config: dict, today: date) -> str:
    chat = config.get("chat", {})
    name = config.get("about", {}).get("name", config["username"])
    return chat_svg.render(
        steps,
        name=chat.get("name", "sand-agent"),
        tagline=chat.get("tagline", "answers from live GitHub history"),
        synced=today.strftime("%b %d").replace(" 0", " "),
        placeholder=chat.get("placeholder", "Ask anything about Sand…"),
        footer=chat.get("footer", "Answers are generated from public GitHub activity every 6 hours."),
        accent=chat.get("accent", "#e5ad23"),
        title=f"{chat.get('name', 'sand-agent')}: a live agent chat about {name}, typed from public GitHub history",
        desc=transcript(steps),
    )


# ---------------------------------------------------------------- readme

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
    """The stats pipeline's outputs add stats and repo tours; the chat still renders without them."""
    try:
        return read_json(path)
    except RuntimeError as exc:
        LOG.warning("Skipping stats data: %s", exc)
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="Offline JSON snapshot with pulls and commits")
    parser.add_argument("--lab-state", type=Path, default=ROOT / "data" / "lab-state.json")
    parser.add_argument("--lab-snapshot", type=Path, default=ROOT / "data" / "snapshot.json")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "harness-chat.svg")
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args()
    try:
        config = read_json(ROOT / "config" / "profile-visuals.json")
        snapshot = read_json(args.fixture) if args.fixture else fetch_snapshot(config, os.getenv("GITHUB_TOKEN", ""))
        lab_state, lab_snapshot = read_optional(args.lab_state), read_optional(args.lab_snapshot)
        work = extract_work_items(snapshot, config)
        steps = build_conversation(work, config, lab_state, lab_snapshot, args.today)
        svg = render_chat(steps, config, args.today)
        readme = update_readme(args.readme.read_text(encoding="utf-8"), readme_block(svg))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
        args.readme.write_text(readme, encoding="utf-8")
        LOG.info("Generated %s: %s questions from %s tasks and %s commits",
                 args.output, sum(step[0] == "user" for step in steps), len(work["tasks"]), len(work["commits"]))
        return 0
    except (OSError, RuntimeError, KeyError, TypeError, ValueError, re.error) as exc:
        LOG.error("Chat generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
