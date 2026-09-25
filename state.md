# Profile system state

- The README opens with the name, badges and one image: `assets/harness-chat.svg`, a dark-mode agent chat that keeps typing forever. Featured work (LadderStar's Open Graph image) follows it. The pixel lab and `assets/lab.svg` were removed on 2026-09-25.

# Stats pipeline

- `scripts/fetch-github-data.py` fetches contributions (GraphQL), public events, recently pushed repos (with description and stars) and the latest workflow conclusion, and writes a trimmed `data/snapshot.json`.
- `scripts/compute-lab-state.py` turns the snapshot into `data/lab-state.json`: six-month totals, active days, peak day, the daily calendar and weekly counts. (The activity/condition/mode fields remain from the lab era and are unused by the chat.)
- `scripts/update_lab.py` runs both in one go and re-exports `ROOT`, `read_json` and `request_json` for the chat generator. `--fixture` computes from an offline snapshot without writing `data/`.
- The default Actions token exposes public contribution history. An optional `LAB_HISTORY_TOKEN` secret with `read:user` adds private contribution counts to the totals. Private repo names never reach the chat.

# Agent chat

- `scripts/update_harness.py` searches the user's public PRs and commits (plus file lists for the newest PRs), reads `data/lab-state.json` and `data/snapshot.json` when present, builds a conversation and renders it with `scripts/chat_svg.py`. It rewrites only the block between `<!-- harness:start -->` and `<!-- harness:end -->` in `README.md`.
- The conversation is a list of beats from `config/profile-visuals.json` `beats`: `intro`, `day-job` (LinkedIn role from `about.career`), `building` (latest PR, plan, files), `shipped` (git-log card of recent commits), `workbench` (public repos with descriptions, two per answer), `stats` (tiles), `habits` (facts computed from commits), `fun` (hand-written `fun_facts`, three per answer) and `contact`. Hand-written answers use `"type": "qa"` with optional `tool`, `think`, `say`, `tiles`, `bullets`, `card` (header plus three-column rows) and `outro`; most resume content (open to work, LadderStar, AI, BloodHound, stack, embassies, Technomads, IT roots, Port Visualizer, mods, numbers, education) lives in these. Beats with no data are skipped. The first and last beats and any beat with `"pinned": true` stay put; the rest reshuffle once per day (`chat.shuffle`).
- Motion: each question types into the input box and is sent as a bubble; "Thinking…" and tool rows collapse to "Thought for Ns" and a result line; answers stream word by word behind per-line cover rects; the chat scrolls. A static copy of the whole conversation sits above the live one so the loop restart is invisible. Everything is SMIL with `repeatCount="indefinite"`, no script.
- Fonts: Liberation Sans/Mono subsets (OFL) are committed in `scripts/fonts/` with `metrics.json` and embedded as woff2 data URIs, so measured wraps match the render; they are metric-compatible with Arial/Courier New as fallbacks. Regenerate with `scripts/build-chat-fonts.py` (needs fonttools and brotli; the workflow never runs it). Characters outside the subset are folded or dropped.
- Personal facts in `about`, `qa` beats and `fun_facts` come only from Sand's resume (shared 2026-09-25), Sand's messages or public profiles Sand pointed to. Never invent them, and keep the phone number and security-office specifics out of the public SVG.
- Offline render: `python scripts/update_harness.py --fixture tests/fixtures/harness-snapshot.json`.
