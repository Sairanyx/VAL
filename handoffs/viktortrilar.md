# viktortrilar: main
**Goal:** work from Valmet's restored PLY; keep a reconstruction side track for comparison
**Done:** validated `Equipment Room.ply` and updated AGENTS.md and docs/CHALLENGE.md to use it; earlier: scene rule, scoring, Roihu details, gitignore entries, scripts/select_frames.py + test, scripts/reconstruct_pi3.py, scripts/reconstruct_colmap.py and their sbatch files; 1,500 frames at `/scratch/project_2020113/sinceai/data/valmet_frames`
**Verified:** all 1,676,481 PLY records valid; plots show the whole room with a dense floor (+y down, floor y of about 1.25); routing not tested. ruff passes; pytest 4 passed, 1 skipped (no torch). Pi3X 100 frames ran (29.2 GB peak), plan view fragmented
**Roihu:** COLMAP job 2920828 still mapping at 22:11, 891 frames in the current model, about 7.8 GB RAM (matching took 466 s; `sinceai/runs/colmap_1500`, log `sinceai/logs/colmap-2920828.out`). OpenBLAS capped in sbatch; "Bad memory unallocation" lines still logged, so check the result. Connect with `-o CertificateFile=` pointing at the repo cert, valid to 2026-11-07 20:41
**On-site rule:** demo must run offline on a local 5090 with a tablet on its network (AGENTS.md, docs/PLAN.md)
**Entire:** `make entire` (scripts/setup_entire.sh) tested in a throwaway clone and run here. Repo now private, so checkpoints sync to origin; real sync and resume untested
**Docs:** added docs/ENTIRE.md and docs/RESULTS.md; updated README, PITCH, CHALLENGE, PLAN, AGENTS from the brief
**Team:** split work across 5 in docs/PLAN.md and AGENTS.md, with fixtures/sample_assets.json. Teammates can't see it until it's pushed
**Next:** push so the team can start; build the PLY loader and cleaning step, then floor and occupancy grid; check the COLMAP result; ask Valmet about the missing CSV and RAG files; check GitHub CI ran; teammates run `make entire`
**Blockers:** none. Own splat is confirmed allowed: use it only if it beats `Equipment Room.ply`. If COLMAP gives one clean model, train 3DGS and compare
