# Since AI Hackathon 2026 — <team name>

> One-line pitch goes here.

## Setup (once)
Needs: `git`, `make`, NVIDIA driver. One line (Linux) — installs uv, clones, sets up, checks GPU:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env && git clone https://github.com/Sairanyx/Newbies.git && cd Newbies && make setup && make gpu
```
Should end by printing your GPU name.

## Commands
| Command | What it does |
|---|---|
| `make train` | Train a model |
| `make tb` | Training graphs at http://localhost:6006 |
| `make fmt` | Tidy code style and auto-fix lint |
| `make check` | Lint and test: run before opening a PR |
| `make up` | Train inside Docker |

## Team workflow
- Work on a `name/feature` branch, not `main`. Keep it small and merge within a couple of hours.
- Rebase on `main`, run `make check`, then open a PR. CI must pass before merging.
- Keep your handoff in `handoffs/<name>.md`, so a teammate or agent can pick up your work.
- Coding agents follow [AGENTS.md](AGENTS.md). Fill in the team areas and the challenge there.
- Keys go in `.env` (copy `.env.example`), never in git.

## Structure
| Path | What it is |
|---|---|
| `app/train.py` | Training code — fill in data, model, loss |
| `app/gpu_check.py` | GPU test |
| `data/` | Datasets (not in git) |
| `runs/` | Training results + saved models (not in git) |
| `lumi/` | Run on the LUMI supercomputer ([guide](lumi/README.md)) |
| `docs/` | Plan, pitch, live schedule |
| `tests/` | Tests, run by `make test` and CI |
| `handoffs/` | Each person's current status |

## Pre-existing work
The setup in the first commits was made before the event. Everything after was built at Since AI 2026.
