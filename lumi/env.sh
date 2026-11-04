# Source this on LUMI: `source lumi/env.sh`
export PROJECT=${PROJECT:-project_XXXXXXXXX}
# Newest LUMI PyTorch container (override with SIF=... if you want a specific one)
export SIF=${SIF:-$(ls -1 /appl/local/containers/sif-images/lumi-pytorch-rocm-*.sif 2>/dev/null | sort -V | tail -1)}
export HF_HOME=/scratch/$PROJECT/$USER/hf_cache
export UV_CACHE_DIR=/scratch/$PROJECT/$USER/uv_cache
export SINGULARITY_BIND=/scratch/$PROJECT,/flash/$PROJECT,/appl/local/containers
echo "Using container: $SIF"
