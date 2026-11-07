# viktortrilar: viktor/keep-faint-splats
**Goal:** demo on Valmet's original `Equipment Room.ply`, with objects built from undamaged renders
**Done:** found that `clean_mask` (opacity above 0.05) removed 30% of splats and caused the black holes, in both scenes. Default is now 0.001. Corrected docs/RESULTS.md: the 26.57 vs 11.82 dB result is retracted, as Valmet's scene is a different capture
**Verified:** app/scene/load.py tests pass. Own splat on 40 frames: 22.31 dB uncleaned, 17.48 dB with the old cleaning. Uncleaned Valmet looks near-photographic by eye from every viewpoint tried
**Roihu:** pipeline job 2926409 on the original: `data/scene/valmet_full`, `data/masks_v3`, `runs/lift_v3`. Default test job 2926421. Original at `data/scene/equipment_room/original.ply`. Cert valid to 2026-11-07 20:41
**Next:** compare lift_v3 with objects-v1, and agree with Eduard before replacing it, because object IDs and `assets_mapped.json` change. Then pick P-005 again, label from real frames, and publish with a make target. Viewer should load the uncleaned original, not `light_full.ply`
**Blockers:** none. Open: which pump is P-005 (obj-0046 is a test pick). Floor map assumes our walked path carries over to Valmet's scene, where objects differ
