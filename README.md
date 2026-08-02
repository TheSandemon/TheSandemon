<div align="center">

# Kyle Touchet

**CREATIVE TECHNOLOGIST**

*Bridging the gap between human imagination and machine intelligence.*
*Building digital experiences that feel alive.*

[![Portfolio](https://img.shields.io/badge/sand.gallery-E5AD23?style=for-the-badge&labelColor=07170D)](https://sand.gallery)
[![Email](https://img.shields.io/badge/contact-07170D?style=for-the-badge&labelColor=8A7135)](mailto:kyletouchet@gmail.com)

</div>

---

## What I build

My work spans **games, digital utilities, and AI-powered production systems**. I focus on projects that merge technical complexity with a strong aesthetic identity — software that looks beautiful, feels premium, and functions flawlessly.

I ship. Everything below is a real thing with real users, not a tutorial repo.

**🖥️ Desktop & web tools** — Electron + TypeScript apps with hardened IPC, real test suites, and CI that packages signed installers.

**🤖 AI-native systems** — multi-agent orchestration, live voice-to-voice interviewing, node-graph agent pipelines. I don't bolt an LLM onto a form; I design around what these models are actually good at.

**🎮 Games & mods** — NeoForge Java mods with physics integration, procedural generation, and persistence that survives a server restart. Published on CurseForge and Modrinth.

---

## Featured work

| Project | What it is | Stack |
|---|---|---|
| **[LadderStar.com](https://ladderstar.com)** 🔒 | An AI-powered career platform. Live voice-to-voice AI audition room over Google's Gemini Multimodal Live API, plus a job board, public talent/employer/coach profiles, token-based employer screenings with consent-gated recording, real-time messaging, admin console, and TipTap blog publishing. | Next.js · TypeScript · Firebase · Gemini Live API · Stripe · Tailwind · Vitest · Vercel |
| **[Technomads.fun](https://technomads.fun)** 🔒 | An AI-powered Minecraft *Create: Aeronautics* server and its whole platform — public site, Stripe-backed memberships, SFTP/RCON server automation, a Discord bridge, a custom launcher/player client, and the airship mods the server runs on. | Next.js · TypeScript · Firebase · Stripe · Vercel Queue · SSH2/SFTP · RCON · WebSockets · discord.js · Java/NeoForge |
| **[BloodHound](https://github.com/TheSandemon/BloodHound)** | A safety-first canine bloodwork and nutrition discussion guide. Turns the high/low/in-range flags on a lab report into conservative food considerations and better questions for a vet — 40 biomarkers across four physiological systems, 70+ breed profiles, cross-marker pattern context, and AAHA-style energy estimates. Fully browser-local: no accounts, uploads, analytics, or server-side health data. | Next.js · TypeScript · React · Zod · Vitest · Vercel |
| **[Port Visualizer](https://github.com/TheSandemon/port-visualizer)** | Windows desktop app for inspecting and managing active network ports. Live diffing, process-grouped views, UAC elevation for protected kills, tray integration. Replaces squinting at `netstat -ano`. | TypeScript · Electron · React · Vitest · GitHub Actions |
| **[TNM Aeronautics Quests](https://github.com/TheSandemon/aeronautics_delivery_quests)** | Procedural hauling contracts for Minecraft airships. Compiles schematics into physics rigid bodies, generates dry-land routes across async chunk loading, tracks cargo that fractures mid-flight. | Java · NeoForge · Create: Aeronautics · Sable physics |
| **[Aeronautics Preflight Checklist](https://github.com/TheSandemon/aeronautics_preflight_checklist)** | Client-side flight diagnostics — simulates mass, lift, center-of-lift offset, and thrust torque imbalance at max power before you launch a brick into the sky. | Java · NeoForge · Custom GUI |

🔒 = shipped and live, source private. Happy to walk through the code or architecture on request.

---

## Also in the workshop

Not all of it is public yet, but this is where my time actually goes:

- **Aegis** — a multi-agent operating system. Autonomous agents work as first-class contributors on a visual Kanban board: reasoning, running commands, cloning repos, opening PRs, and managing their own task lifecycle.
- **Audition** — the standalone desktop counterpart to LadderStar's audition room. Live voice-to-voice mock interviews over the Gemini Live API: real bidirectional audio, five interviewer personas, four difficulty levels, tailored to your resume and the job description, scorecard at the end.
- **Aurel** — Electron + Three.js audio visualizer with six 3D environments, GPU instancing, and a deterministic offline renderer that samples audio at exact frame timestamps and muxes to H.264/AAC at up to UHD/60.
- **Aints** — thousands of ants on flat NumPy state tensors, sampling pheromone and density grids under caste-conditioned neural policies, with evolutionary selection over colony genomes.

---

## Stack

**Languages** · TypeScript · JavaScript · Python · Java · HTML/CSS · GLSL · Bash · PowerShell

**Frontend** · React · Next.js · Vite · Svelte · Preact · Tailwind · Framer Motion · Zustand · TanStack Query · React Router · React Flow · dnd kit · TipTap · Lucide · Radix-style primitives

**Graphics & media** · Three.js · WebGL · PixiJS · Web Audio API · Canvas · FFmpeg · pdf.js

**Desktop** · Electron · electron-vite · electron-builder · electron-toolkit · node-pty · xterm.js

**Backend & infra** · Node · Express · FastAPI · Uvicorn · WebSockets · REST · Firebase (Auth, Firestore, Storage, Functions, Admin, Rules) · Vercel (Queue, Analytics, Speed Insights, Cron) · Stripe · Resend · SSH2/SFTP · RCON · Discord.js · OpenTelemetry

**Data & scientific** · NumPy · pandas · Pydantic · Zod · GSON/JSON registries · IndexedDB · ccxt

**Games & simulation** · NeoForge · Minecraft modding (Create, Create: Aeronautics, Sable physics, Flywheel, Ponder, Registrate, FTB) · Gradle · Godot · Unreal Engine tooling · Satisfactory modding · evolutionary/neural policy simulation

**Web3** · OnchainKit · wagmi · viem

**Testing & tooling** · Vitest · Playwright · pytest · Testing Library · ESLint · Prettier · oxlint · TypeScript compiler · GitHub Actions · Git · Docker

**AI — model providers** · Anthropic · Google (Gemini, incl. Multimodal Live API) · OpenAI · DeepSeek · Meta Llama · Hugging Face · Replicate · Ollama · llama.cpp (local inference)

**AI — generative media** · Midjourney · Stability AI · Runway · Luma · Kling · ElevenLabs · Suno *(routed through Replicate)*

**AI — agent engineering** · Claude Code · Gemini CLI · Codex CLI · Antigravity CLI · Model Context Protocol (MCP) · custom agent skills & subagents · multi-agent orchestration · tool/function calling · RAG · prompt & context engineering · evals

---

## On working with AI

I build *with* these models, deliberately and in the open. My commit history has agents in it and I'm not going to pretend otherwise — I'd rather be judged on whether the thing works, ships, and holds up under review.

What I've found is that the interesting problem was never "can it write the function." It's orchestration: how you decompose work, where you put the guardrails, what state survives a context window, and when a human has to make the call. That's the problem I keep building tools for.

---

<div align="center">

*When I'm not writing code, I'm designing, compiling ideas, and exploring new systems.*
*I believe the web is an evolving medium where creative ideas are still waiting to be unlocked.*

**[sand.gallery](https://sand.gallery)**

</div>
