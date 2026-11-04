# Running on LUMI (AMD MI250X GPUs, ROCm)

LUMI has **no Docker** and its GPUs are **AMD** -> we use LUMI's prebuilt
PyTorch+ROCm Singularity container and add our other deps on top with uv.

## One-time setup (on a LUMI login node)
```bash
export PROJECT=project_XXXXXXXXX          # <- our LUMI project id
cd /scratch/$PROJECT/$USER
git clone <repo-url> sinceai && cd sinceai
bash lumi/setup.sh
```

## Run a job
```bash
sbatch lumi/train.sbatch          # edit the command at the bottom
squeue --me                       # check queue
tail -f logs/*.out
```

## Quick interactive GPU shell (debugging)
```bash
srun -p small-g --gpus-per-node=1 -t 00:30:00 -A $PROJECT --pty \
  singularity exec $SIF bash -c 'source .venv-lumi/bin/activate && python'
```

## Notes
- Put data/models in `/scratch/$PROJECT` or `/flash/$PROJECT`, NOT `$HOME` (tiny quota).
- 1 MI250X = 2 GCDs; Slurm/PyTorch see **8 "GPUs" per node** (`--gpus-per-node=8`).
- Set `HF_HOME` to scratch so model downloads don't fill `$HOME`.
- In code, `torch.cuda.*` works as normal on ROCm (`device="cuda"`).
- Container list: `ls /appl/local/containers/sif-images/`
  (pick the newest `lumi-pytorch-rocm-*.sif` and set it in `lumi/env.sh`).
