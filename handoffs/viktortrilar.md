# viktortrilar: viktor/moving-splats
**Goal:** dragging moves the real object, the floor behind looks whole, and operators can add missed objects
**Done:** app/scene/split_movable.py cuts objects down to the floor, and clones nearby floor under them (patches.json records where). app/api/select_object.py and web/addobject.js: drag a box or tap, a vision model suggests a label, code sets mobility, the operator confirms. PRs #10, #11, #12 merged. PR #13 is open on this branch
**Verified:** lint; 175 tests before the patch work, split tests pass since. Browser: real drag, add, save, re-route, undo. Selection median overlap 0.35 against known boxes. Qwen 9B sensible on 6 crops. Patch render job 2928589 running. Not tested: 5090, tablet, full scene in the viewer
**Next:** read `runs/floor_v2/patch_final.jpg`, commit the patch, update PR #13. Rehearse on the 5090 offline. Mask-based cutting for more objects. Written directions. A person confirms P-005 on obj-0049
**Blockers:** none. Cert valid to 2026-11-07 20:41. Local branch viktor/viewer-objects holds an unused merge: don't merge it
