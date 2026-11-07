#!/bin/bash
# Usage: sbatch scripts/roihu_render.sbatch SCENE_ID MAX_VIEWS OUT_NAME [render.py options].
# Run from /scratch/project_2020113/sinceai.
#SBATCH --job-name=sinceai_render
#SBATCH --account=project_2020113
#SBATCH --partition=vizinteractive
#SBATCH --nodes=1 --ntasks=1 --cpus-per-task=16 --mem=120G
#SBATCH --gres=gpu:l40:1 --time=01:00:00
#SBATCH --output=/scratch/project_2020113/sinceai/logs/render-%j.out
set -euo pipefail

SCENE=$1
VIEWS=$2
OUT=$3
shift 3
ROOT=/scratch/project_2020113/sinceai
ENVS=/scratch/project_2020113/inspection

# gsplat compiles its CUDA code on first use, for the L40's architecture.
export CUDA_HOME="$ENVS/cuda-home" TORCH_CUDA_ARCH_LIST=8.9
export PATH="$CUDA_HOME/bin:$ENVS/venv-3dgs/bin:$PATH"

cd "$ROOT/code"
"$ENVS/venv-3dgs/bin/python" -u -m app.scene.render \
    "$ROOT/data/scene/$SCENE/clean.ply" "$ROOT/data/scene/$SCENE/$OUT" --max-views "$VIEWS" "$@"
