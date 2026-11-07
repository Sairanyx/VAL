# viktortrilar: viktor/bim-model-fixes
**Goal:** merge Sasha's BIM mode with fixes for what checking it found, keeping Sasha's commit as is
**Done:** merged `yasasha/bim`. app/extract/primitives.py rejects cylinders from nearly flat arcs, and `make shapes` applies that to the Release's copy (`make bim` runs it). web/bim.js shows objects made in the viewer as plain boxes. USAGE says what the IFC leaves out
**Verified:** 223 tests passed, 2 skipped, lint clean. Real data: only `obj-0144` changes (now a box), 0 IFC schema issues. Headless browser: split parts show in BIM mode at the right places, undo removes them, no page errors. Not tested: a real BIM tool, 5090, tablet
**Next:** rebase `viktor/bim` on this: Plan screen and DXF only, Sasha's wall estimate, Plan screen fixes, IFC download that includes operator changes
**Blockers:** an agent is fixing routes that ignore moved objects on `viktor/route-keeps-moved-objects`, not finished. Roihu closed until at least Monday. Local branch viktor/viewer-objects holds an unused merge: don't merge it
