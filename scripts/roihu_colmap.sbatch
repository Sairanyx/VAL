#!/bin/bash
# Usage: sbatch scripts/roihu_colmap.sbatch. Run from /scratch/project_2020113/sinceai.
#SBATCH --job-name=sinceai_colmap
#SBATCH --account=project_2020113
#SBATCH --partition=interactive
#SBATCH --nodes=1 --ntasks=1 --cpus-per-task=32 --mem=60G
#SBATCH --time=12:00:00
#SBATCH --output=/scratch/project_2020113/sinceai/logs/colmap-%j.out
set -euo pipefail

ROOT=/scratch/project_2020113/sinceai
ENVS=/scratch/project_2020113/inspection

# pycolmap's bundled OpenBLAS crashes during loop detection with more threads than this.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4 "$ENVS/venv-colmap/bin/python" -u "$ROOT/scripts/reconstruct_colmap.py" \
    "$ROOT/data/valmet_frames" "$ROOT/runs/colmap_1500" \
    --vocab-tree "$ROOT/models/vocab_tree_faiss_flickr100K_words256K.bin"
