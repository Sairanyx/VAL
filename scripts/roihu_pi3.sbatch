#!/bin/bash
# Usage: sbatch scripts/roihu_pi3.sbatch [FRAME_COUNT]. Run from /scratch/project_2020113/sinceai.
#SBATCH --job-name=sinceai_pi3
#SBATCH --account=project_2020113
#SBATCH --partition=vizinteractive
#SBATCH --nodes=1 --ntasks=1 --cpus-per-task=16 --mem=120G
#SBATCH --gres=gpu:l40:1 --time=01:00:00
#SBATCH --output=/scratch/project_2020113/sinceai/logs/pi3-%j.out
set -euo pipefail

FRAMES=${1:-100}
ROOT=/scratch/project_2020113/sinceai
ENVS=/scratch/project_2020113/inspection

nvidia-smi --query-gpu=name,memory.free --format=csv,noheader
PYTHONPATH="$ROOT/pydeps" HF_HUB_OFFLINE=1 "$ENVS/venv-l40/bin/python" -u "$ROOT/scripts/reconstruct_pi3.py" \
    "$ROOT/data/valmet_frames" "$ROOT/runs/pi3_${FRAMES}" \
    --weights "$ENVS/src/data/external/pi3/weights" --frames "$FRAMES"
