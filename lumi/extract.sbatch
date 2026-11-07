#!/bin/bash
# Asset extraction on LUMI. SAM3 masks run as 8 array tasks of one GPU each, sharing the views;
# merge, label, and assets run once after them. From the repo root on LUMI:
#
#   sbatch --account=$PROJECT --array=0-7 lumi/extract.sbatch masks
#   sbatch --account=$PROJECT --dependency=afterok:<masks job id> lumi/extract.sbatch rest
#
# Needs: bash lumi/setup.sh once, the scene in data/scene/equipment_room (clean.ply, render,
# render_detail), and model weights downloaded on a login node. See "Asset extraction" in
# lumi/README.md.
#SBATCH --job-name=extract
#SBATCH --partition=small-g
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=7
#SBATCH --mem=60G
#SBATCH --time=03:00:00
#SBATCH --output=logs/%x-%A_%a.out

set -euo pipefail
STAGE=${1:?usage: extract.sbatch masks|rest}
SCENE=${SCENE:-data/scene/equipment_room}
VLM=${VLM:-Qwen/Qwen3-VL-8B-Instruct}
TASKS=${SLURM_ARRAY_TASK_COUNT:-1}
TASK=${SLURM_ARRAY_TASK_ID:-0}
source lumi/env.sh
export HF_HUB_OFFLINE=1

if [ "$STAGE" = masks ]; then
  CMD="python -m app.extract masks --scene $SCENE --shard $TASK/$TASKS"
else
  CMD="python -m app.extract merge --scene $SCENE && \
       python -m app.extract label --scene $SCENE --vlm-model $VLM && \
       python -m app.extract assets --scene $SCENE"
fi
singularity exec "$SIF" bash -c "source .venv-lumi/bin/activate && $CMD"
