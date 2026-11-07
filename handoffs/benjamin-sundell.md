# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** route arrows: chevrons flow along the route towards the target, a faint guide line underneath, a pulsing end ring, and arrows vanish behind the walker (`web/route.js`, one `route?.animate(dt)` line in `web/main.js`). Branch is up to date with main (Viktor's routes, copilot, moving splats, add object)
**Verified:** `make check` passes (168 passed, 16 skipped). Arrows NOT yet seen in a browser: needs `make api` + `make web` with the real floor map
**Next:** look at the arrows in the browser and tune spacing/size/speed (constants at the top of route.js); demo video and slides
**Blockers:** none
