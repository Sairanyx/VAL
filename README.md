# Since AI Hackathon 2026 — <team name>

> One-line pitch goes here.

## Setup (once)
Needs: `git`, `make`, [`uv`](https://docs.astral.sh/uv/), NVIDIA driver.
```bash
git clone <repo-url> && cd <repo>
make setup
make gpu        # should print your GPU name
```

## Commands
| Command | What it does |
|---|---|
| `make train` | Train a model |
| `make tb` | Training graphs at http://localhost:6006 |
| `make fmt` | Tidy code style |
| `make up` | Train inside Docker |

## Structure
| Path | What it is |
|---|---|
| `app/train.py` | Training code — fill in data, model, loss |
| `app/gpu_check.py` | GPU test |
| `data/` | Datasets (not in git) |
| `runs/` | Training results + saved models (not in git) |
| `lumi/` | Run on the LUMI supercomputer ([guide](lumi/README.md)) |
| `docs/` | Plan, pitch, live schedule |

## Pre-existing work
The setup in the first commits was made before the event. Everything after was built at Since AI 2026.
