#!/bin/bash
# Creates .venv-lumi on top of the container's torch (no torch reinstall).
set -euo pipefail
source "$(dirname "$0")/env.sh"
mkdir -p logs "$HF_HOME"
singularity exec "$SIF" bash -c '
  python -m venv --system-site-packages .venv-lumi
  source .venv-lumi/bin/activate
  pip install -q uv
  uv export --no-hashes --no-dev --no-emit-project \
    | grep -vE "^(torch|torchvision)==" > /tmp/req-lumi.txt
  uv pip install -r /tmp/req-lumi.txt
  python -c "import torch; print(\"torch\", torch.__version__, \"GPUs:\", torch.cuda.device_count())"
'
