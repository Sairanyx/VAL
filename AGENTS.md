# Agent guidelines

Since AI Hackathon 2026, 5-person team. Several people and agents work here at once.
This file is loaded with every prompt, so keep it short.

## Project status
- Main challenge: Valmet's Industrial Metaverse, semantic 3D scene understanding and a field-service
  copilot. Requirements and data problems: `docs/CHALLENGE.md`. Read it before pipeline work.
- The demo scene is Valmet's uncleaned `Equipment Room.ply`. Don't use the damaged `Industrial Boiler
  Room` copy or our own splat, which looks worse. Keep scenes out of git. Never run `clean_mask` on
  anything people see or that views are rendered from: it leaves black holes.
- Current tasks and how to run the demo: `docs/PLAN.md`, under "Now".
- Keep pipeline code independent of which scene file it loads.
- The demo must run with no internet, on a laptop: ours, or a judge's from the zip (`make bundle`). No
  cloud APIs, hosted models, or CDN assets at runtime. Roihu is for development experiments only.
- Scoring: asset extraction 30%, navigation 25%, AI diagnostics 20%, backend 15%, demo 10%. Put
  backend and spatial work first, keep the UI lightweight, and build no mobile app.
- Never invent asset identity. Store how each asset was mapped and with what confidence.
- Sponsor challenges are optional extras. Don't add a sponsor integration unless asked.

## Team areas
Stay in your person's area. Ask before making large changes in someone else's.

| Person | Area |
|---|---|
| Viktor | Scene loading, rendering, moving objects (`app/scene/`) |
| Sasha | Asset extraction and 3D boxes (`app/extract/`) |
| Eduard | Floor, routing, nearby search, backend API (`app/nav/`, `app/api/`) |
| Hannu | Excel data, asset mapping, AI copilot (`app/copilot/`) |
| Benjamin | Web viewer, tablet, demo video, slides (`web/`, `docs/`) |

Tasks, shared data formats, and API: `docs/PLAN.md`. Build against `fixtures/sample_assets.json`.

## Saving tokens
- Find code with Entire Graph if it's installed, otherwise `rg` or `git grep`. Read only the lines
  you need, and don't scan the whole repo.
- Don't read `uv.lock`, `data/`, `runs/`, or logs unless the task requires it. Use `tail` on logs.
- Don't re-read files you just edited, and don't repeat tool output back in replies.
- Keep replies short: what changed, what was verified, what's next.
- Use subagents only when a task truly needs them.
- Start a new session for each new task, and resume from the handoff instead of old chat.
- Use the cheapest model that can do the job.

## Git
- Never commit directly to `main`. It must always run, because it's what we demo.
- Before editing anything, check the current branch. If it's `main`, run `git pull`, then create a
  `name/feature` branch. Ask the user for their name if you can't tell it from `git config user.name`.
- Keep branches small and merge within a couple of hours.
- Rebase on `main` before opening a PR, and PR only when `make check` passes.
- Change `pyproject.toml` and `uv.lock` in their own small PR. Add packages with `uv add`.
- If running agents in parallel, give each its own git worktree.
- Never commit secrets (use `.env`, and list new names in `.env.example`), datasets, or checkpoints.
- Never force-push `main` or rewrite someone else's branch.

## Private repo
This repo is private for now, and Entire syncs session transcripts to it. Never paste secrets into
prompts or commit Valmet's data. Before making it public, follow `docs/ENTIRE.md`.

## Before finishing a prompt
1. If code changed, run `make check` and fix failures. Report failures you can't fix.
2. If files changed, update your handoff (below). Commit it together with your work.
3. If a run produced numbers worth keeping, add a line to `docs/RESULTS.md`.

## Handoff
Your file is `handoffs/<name>.md`, where `<name>` is `git config user.name`, lowercased, with
spaces replaced by hyphens. Overwrite it each time and keep it under 15 lines:

```markdown
# <name>: <branch>
**Goal:** what this work is for
**Done:** what changed, with key files
**Verified:** what was run, and the result
**Next:** the next concrete step
**Blockers:** anything stuck, or "none"
```

At the start of a session, read your own handoff. Read a teammate's only if your task touches
their area.

## Commands
| Command | Use |
|---|---|
| `make check` | Lint and test: run before finishing |
| `make lint` | Format check and ruff only (no torch needed) |
| `make test` | pytest |
| `make fmt` | Auto-fix style |
| `make scene` | Get objects, floor map, and light scenes: then `make mapping` |
| `make pieces` | Cut movable objects out of the scene |
| `make laptop-model` | Get Val's small model, for a laptop with no GPU |
| `make model` | Get Val's larger model, for a GPU, before going offline |
| `make voice-model` | Get the speech model for talking to Val, before going offline |
| `make pipeline` | Run a scene through everything, from `scenes/*.toml` |
| `make bundle` | Build `dist/val-demo.zip`, which runs on someone else's laptop |
| `make train` | Train a model |

- Python 3.12, managed by uv. Use `uv run` and `uv add`, not `pip`.
- Put tests in `tests/`. Use `pytest.importorskip("torch")` for tests needing torch or other heavy
  dependencies, because CI runs without them.

## Compute
| Machine | Use for |
|---|---|
| ThinkPads | Coding and small CPU runs |
| RTX 5090 | Quick GPU training and experiments (shared, so check `nvidia-smi` first) |
| LUMI | Large jobs. AMD GPUs and no Docker: follow `lumi/README.md` |
| Roihu | Project `project_2020113`, work in `/scratch/project_2020113/sinceai`. x86 L40 GPUs via `vizinteractive` (12 h limit). GH200 nodes are ARM with a long queue |

## Hackathon rules
- Keep the README's "Pre-existing work" section accurate.
- A working demo beats clean abstractions. Avoid building for needs we don't have yet.

<!-- entire-agent:begin -->
Read .entire/agent-guide.md for this repository's workflow, source inspection, and verification guidance.
@.entire/agent-guide.md
<!-- entire-agent:end -->
