# Agent guidelines

Since AI Hackathon 2026, 5-person team. Several people and agents work here at once.
This file is loaded with every prompt, so keep it short.

## Project status
- Main challenge: not chosen yet. Replace this line with it once announced.
- Sponsor challenges are optional extras. Don't add a sponsor integration unless asked.

## Team areas
Stay in your person's area. Ask before making large changes in someone else's.

| Person | Area |
|---|---|
| TBD | TBD |

## Saving tokens
- Search first (`rg`, `git grep`), then read only the lines you need. Don't scan the whole repo.
- Don't read `uv.lock`, `data/`, `runs/`, or logs unless the task requires it. Use `tail` on logs.
- Don't re-read files you just edited, and don't repeat tool output back in replies.
- Keep replies short: what changed, what was verified, what's next.
- Use subagents only when a task truly needs them.
- Start a new session for each new task, and resume from the handoff instead of old chat.
- Use the cheapest model that can do the job.

## Git
- Never commit directly to `main`. It must always run, because it's what we demo.
- Branch as `name/feature`. Keep branches small and merge within a couple of hours.
- Rebase on `main` before opening a PR, and PR only when `make check` passes.
- Change `pyproject.toml` and `uv.lock` in their own small PR. Add packages with `uv add`.
- If running agents in parallel, give each its own git worktree.
- Never commit secrets (use `.env`, and list new names in `.env.example`), datasets, or checkpoints.
- Never force-push `main` or rewrite someone else's branch.

## Before finishing a prompt
1. If code changed, run `make check` and fix failures. Report failures you can't fix.
2. If files changed, update your handoff (below). Commit it together with your work.

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
| Roihu | No setup in this repo yet. Check its GPU type and architecture before using it |

## Hackathon rules
- Keep the README's "Pre-existing work" section accurate.
- A working demo beats clean abstractions. Avoid building for needs we don't have yet.
