# yasasha: yasasha/extract
**Goal:** asset extraction (30% of score): SAM3 masks on rendered views → splats → objects → Qwen3-VL labels → `assets.json` + `splat_labels.npy`
**Done:** `app/extract/` (geometry, masks, merge, label, `python -m app.extract masks|merge|label|assets`), `tests/test_extract.py`, `lumi/extract.sbatch` + "Asset extraction" in lumi/README.md. `splat_labels.npy` indexes `clean.ply` (1,178,554 splats)
**Verified:** make check passes (28 tests). SAM3 runs on the GTX 1650 but float16 gives NaN masks; float32 works but takes about 55 s per pass. Code now picks bfloat16 where supported, float32 otherwise. Merge and label not yet run on real masks
**Laptop GPU:** project torch needs CUDA 13.2 and the WSL driver is 12.6, so use `~/.venvs/extract-cu126/bin/python -m app.extract ...`
**Next:** run masks on LUMI (8-GPU array), check `extract/overlays/`, then merge/label/assets; tune link thresholds; count assets for docs/RESULTS.md
**Blockers:** none. HF token was pasted in chat, so rotate it after downloading models
