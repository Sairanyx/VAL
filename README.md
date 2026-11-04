# Since AI Hackathon 2026 — <team name>

> One-line pitch goes here.

## Setup (once)
Needs: `git`, `make`, [`uv`](https://docs.astral.sh/uv/), NVIDIA driver.
```bash
git clone <repo-url> && cd <repo>
make setup      # installs everything (GPU PyTorch) + creates .env
make gpu        # check your GPU is found
```
Put your API keys in `.env`, then `make keys` to test them.

## Commands
| Command | What it does |
|---|---|
| `make train` | Train a model (`app/train.py`) |
| `make tb` | Training graphs at http://localhost:6006 |
| `make dev` | Start backend at http://localhost:8000/docs |
| `make ui` | Start demo page at http://localhost:8501 |
| `make test` | Run tests |
| `make fmt` | Auto-fix code style |
| `make models` | Download small pretrained models |
| `make keys` | Check API keys in `.env` work |
| `make up` | Run everything in Docker |
| `make deploy` | Put the demo on our VPS |
| `make zip` | Make the source .zip for submission |

## Structure
| Path | What it is |
|---|---|
| `app/train.py` | Training template (fill in data, model, loss) |
| `app/main.py` | Backend API |
| `app/ui.py` | Demo web page |
| `app/llm.py` | Call AI APIs (Claude, Gemini, ...) |
| `app/gpu_check.py` | GPU test |
| `scripts/` | Helper scripts (key check, model download, zip) |
| `tests/` | Tests |
| `data/` | Datasets (not in git) |
| `runs/` | Training results + saved models (not in git) |
| `notebooks/` | Experiments |
| `lumi/` | Run on the LUMI supercomputer ([guide](lumi/README.md)) |
| `deploy/` | Hosting on the VPS |
| `docs/` | Plan, pitch, live schedule |
| `.env` | Your API keys (never commit!) |

## Rules for us
- Work on a branch, open a PR, merge to `main` often. `main` must always run.
- Never commit `.env` or big data files.

## Pre-existing work
Everything in the first commit ("Pre-event boilerplate") was made before the event.
Everything after it was built at Since AI 2026.
