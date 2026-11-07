# viktortrilar: viktor/viewer-objects (draft PR #3)
**Goal:** demo on own splat: real objects, floor, routes, P-005
**Done:** app/nav/carve.py removes floaters using rendered views; grid.py takes `--views` and `--walked`; scripts/camera_path.py exports the camera path; routes return `view_from` (2 m back). P-005 candidate is obj-0048 with `manual_visual_unconfirmed`, confidence 0.3
**Verified:** lint passes; 99 tests passed, 2 skipped (no torch). Real grid: 6.6 m2 connected at 0.6 m (was 0.2). 7 rendered views along the route look clear, by eye. /api/route tested locally on the real grid and assets
**Roihu:** `data/scene/splat_v2/{clean.ply,light_full.ply,nav_grid_carved.npz,walked.npy}`, `runs/lift_v2`, `runs/floor_v2`. Local overrides: scratchpad `overrides_v2.json`. Cert valid to 2026-11-07 20:41
**Next:** a person confirms P-005 and which of the two pumps. Publish a `scene-v2` Release if Viktor agrees. Viewer doesn't draw routes yet (Benjamin's area). Decide on Eduard's PR #2, which duplicates A*. Redo the AI label review for the new scene
**Blockers:** none. Open: whether scene units are truly metres; object labels are mostly `unsure`/`unknown` on the new scene
