# viktortrilar: viktor/scene-full
**Goal:** demo on own splat: real objects, floor, routes, P-005
**Done:** PR #3 is merged by Eduard, who kept Viktor's routing and added heights. This branch adds `make scene-full`, which gets `clean.ply` (513 MB, view-dependent color) from Release `scene-v2`. Local branch viktor/viewer-objects holds an unused merge, 9338915: don't push or merge it
**Verified:** on main's code with `make scene` data: person route to obj-0048 6.8 m, robot 6.7 m. main's CI passes; 113 tests passed, 17 skipped locally
**Roihu:** `data/scene/splat_v2/{clean.ply,render,render_detail}`, `runs/lift_v2`, `runs/floor_v2`. Cert valid to 2026-11-07 20:41
**Next:** a person confirms P-005 and which of the two pumps (obj-0048 is an unconfirmed pick, confidence 0.3). Viewer doesn't draw routes yet (Benjamin's area). `make floor` doesn't pass `--views`/`--walked`. Redo the AI label review for the new scene
**Blockers:** none. Open: whether the video was really walked, and whether units are metres. Full scene not tested on a tablet
