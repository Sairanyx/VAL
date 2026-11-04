#!/bin/bash
#SBATCH --job-name=sinceai
#SBATCH --account=project_XXXXXXXXX
#SBATCH --partition=small-g
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=7
#SBATCH --mem=60G
#SBATCH --time=02:00:00
#SBATCH --output=logs/%x-%j.out

source lumi/env.sh
singularity exec "$SIF" bash -c '
  source .venv-lumi/bin/activate
  python -m app.train      # <- change to your script
'
