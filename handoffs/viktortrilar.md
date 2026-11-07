# viktortrilar: viktor/demo-fixes
**Goal:** demo on Valmet's uncleaned `Equipment Room.ply`, with routes and copilot visible in the viewer
**Done:** viewer draws, walks and re-plans routes (web/route.js) and has a copilot panel (web/copilot.js); serve.py forwards /api. `make scene` now gets Release `objects-v2`: 440 objects from the uncleaned scene, labels transferred from the AI review, floor map, light scenes. Copilot refuses bypass requests and quotes measured trends. Floor map: walked path only clears obstacles above 1.2 m. Cleaning (`clean_mask`) is for analysis only
**Verified:** lint; nav-check 12 of 12 on a fresh `make scene`; browser test of routes and copilot with software rendering on light_400k. Not tested: tablet, 5090, full original in the viewer
**Dropped:** real-frame labelling (alignment too coarse for single objects); own splat, stretch limit and floor filling
**Roihu:** `data/scene/valmet_full`, `data/masks_v3`, `runs/lift_v3` (`assets_reviewed.json`, `shapes_reviewed.json`). Cert valid to 2026-11-07 20:41
**Next:** rehearse on the 5090 and a tablet, offline. A person confirms P-005: obj-0049 is an unconfirmed pick (confidence 0.3), one of two inline pumps
**Blockers:** none. Open: whether units are truly metres. Local branch viktor/viewer-objects has an unused merge, 9338915: don't merge it
