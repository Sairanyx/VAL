# viktortrilar: main (split, combine, collisions merged)
**Goal:** let operators correct objects: move safely, split, combine, and see frames clearly, working with the team's highlights and live routes
**Done:** collision check, Split, Combine, frames that hide what's behind them. Fixed clashes with live routes and highlights: routes only follow the camera in walk mode, a refused drop re-plans, collision warnings aren't overwritten
**Verified:** lint; 213 tests passed, 2 skipped. Full flow in a headless browser with pieces, highlights and live routes: refused drop, demo move 4.31 to 5.56 m, split, combine, reload, undo, no page errors. Slow software rendering, light scene. Not tested: 5090, tablet, real model in the browser panel
**Next:** rehearse on the 5090. Build the precision sample from crops rendered on the 5090, as Roihu's masks are out of reach. A person confirms P-005 on obj-0049
**Blockers:** Roihu closed until at least Monday (CSC security notice). A split or combined object's scan piece doesn't split with it. Local branch viktor/viewer-objects holds an unused merge: don't merge it
