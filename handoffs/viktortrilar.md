# viktortrilar: viktor/split-and-occlusion (includes PR #18)
**Goal:** let operators correct objects: move safely, split, combine, and see frames clearly
**Done:** collisions (PR #18). This branch: Split and Combine in the viewer and backend, frames hide what's behind them, `obj-0008` off the moving list. docs/USAGE.md updated
**Verified:** lint; 205 tests passed, 2 skipped. Browser, software rendering, light scene: split, combine, reload, undo, cancel. Not tested: 5090, tablet, frame look on the full scene
**Next:** merge PR #18 and this one. Rehearse on the 5090. Build the precision sample from crops rendered on the 5090, as Roihu's masks are out of reach
**Blockers:** Roihu closed until at least Monday (CSC security notice), past the deadline. Its masks, renders, and frames can't be reached, and they had no other copy. A split or combined object's scan piece doesn't split with it. Local branch viktor/viewer-objects holds an unused merge: don't merge it
