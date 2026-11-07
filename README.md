# Since AI Hackathon 2026 — <team name>

> A navigable digital twin of an industrial plant room for field service, running entirely on site.

Built for Valmet's Industrial Metaverse challenge. It turns a Gaussian splat scan into framed,
labelled assets linked to device data, routes a worker around obstacles to a faulty device, and
gives AI guidance with cited evidence. Runs on one local GPU server, viewed in a tablet browser.

**Status:** in development. [Plan](docs/PLAN.md) · [Challenge](docs/CHALLENGE.md) ·
[Results](docs/RESULTS.md)

## Setup (once)
Needs: `git`, `make`, NVIDIA driver. One line (Linux) — installs uv, clones, sets up, checks GPU:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env && git clone https://github.com/Sairanyx/Newbies.git && cd Newbies && make setup && make gpu
```
Should end by printing your GPU name.

## Commands
| Command | What it does |
|---|---|
| `make db` | Start local TimescaleDB and load the Excel telemetry |
| `make nav-check` | Test floor map, routes, mapping and API together, with a picture |
| `make train` | Train a model |
| `make tb` | Training graphs at http://localhost:6006 |
| `make fmt` | Tidy code style and auto-fix lint |
| `make check` | Lint and test: run before opening a PR |
| `make entire` | Install and enable Entire |
| `make views` | Download rendered views for the scene |
| `make scene` | Download the demo scene, floor map, and objects |
| `make scene-full` | Also download the full-quality scene (513 MB) |
| `make up` | Train inside Docker |

## Team workflow
- Work on a `name/feature` branch, not `main`. Keep it small and merge within a couple of hours.
- Rebase on `main`, run `make check`, then open a PR. CI must pass before merging.
- Keep your handoff in `handoffs/<name>.md`, so a teammate or agent can pick up your work.
- Coding agents follow [AGENTS.md](AGENTS.md).
- Scenes and Valmet's data aren't in git. Get them from Viktor.
- Run `make entire` once to set up session sharing and code search ([guide](docs/ENTIRE.md)).
- Keys go in `.env` (copy `.env.example`), never in git.

## Structure
| Path | What it is |
|---|---|
| `app/` | Pipeline, API, and copilot code ([who owns what](docs/PLAN.md)) |
| `app/train.py` | Training template, not used by the demo so far |
| `app/gpu_check.py` | GPU test |
| `scripts/` | Frame selection, reconstruction, and Roihu jobs |
| `fixtures/` | Fake sample data to build against |
| `data/` | Datasets and generated scene files (not in git) |
| `runs/` | Run outputs and saved models (not in git) |
| `lumi/` | Run on the LUMI supercomputer ([guide](lumi/README.md)) |
| `docs/` | Plan, challenge, results, pitch, Entire setup, live schedule |
| `tests/` | Tests, run by `make test` and CI |
| `handoffs/` | Each person's current status |

## Pre-existing work
The setup in the first commits was made before the event. Everything after was built at Since AI 2026.

Experiments on Roihu reuse Python environments and model weights installed before the event, for
Pi3X and COLMAP. List any other earlier code or tools here if we reuse them.
