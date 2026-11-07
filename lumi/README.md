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

## Asset extraction (SAM3 + Qwen3-VL)
From the repo root on a login node, with `PROJECT` exported and `bash lumi/setup.sh` done:
```bash
source lumi/env.sh
# Scene: copy the views archive and Equipment Room.ply from your laptop, then unpack and clean
mkdir -p data/scene && tar -xf equipment_room_views_v1.tar -C data/scene   # or: make views ARCHIVE=...
singularity exec $SIF bash -c 'source .venv-lumi/bin/activate && \
  python -m app.scene.load "Equipment Room.ply" --out data/scene/equipment_room/clean.ply'
# Models: SAM3 is gated, so log in with an approved account. Download here, as jobs run offline
singularity exec $SIF bash -c 'source .venv-lumi/bin/activate && hf auth login && \
  hf download facebook/sam3 && hf download Qwen/Qwen3-VL-8B-Instruct'
mkdir -p logs
sbatch --account=$PROJECT --array=0-7 lumi/extract.sbatch masks      # 8 GPUs share the views
sbatch --account=$PROJECT --dependency=afterok:JOBID lumi/extract.sbatch rest
```
Outputs: `data/scene/equipment_room/assets.json`, `splat_labels.npy`, and `extract/`. Copy them back
with `rsync`. SAM3 and the VLM use bfloat16 here; float16 gives NaN masks.

## Notes
- Put data/models in `/scratch/$PROJECT` or `/flash/$PROJECT`, NOT `$HOME` (tiny quota).
- 1 MI250X = 2 GCDs; Slurm/PyTorch see **8 "GPUs" per node** (`--gpus-per-node=8`).
- Set `HF_HOME` to scratch so model downloads don't fill `$HOME`.
- In code, `torch.cuda.*` works as normal on ROCm (`device="cuda"`).
- Container list: `ls /appl/local/containers/sif-images/`
  (pick the newest `lumi-pytorch-rocm-*.sif` and set it in `lumi/env.sh`).
