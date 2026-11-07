# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** route arrows: chevrons flow towards the target, faint guide line, pulsing end ring (`web/route.js`, `route?.animate(dt)` in `web/main.js`). Merged latest main and Eduard's unmerged `eduard-live-route` (live re-plans while moving/dragging, trims the line while walking); resolved conflicts in route.js and main.js by keeping both. Arrows now spaced from the route's end so live re-plans and trimming don't make them jump
**Verified:** `make check` passes (192 passed). Arrows and live re-plan NOT yet seen together in a browser: needs `make mapping`, `make api`, `make web`
**Next:** check in the browser; open a PR to main (coordinate with Eduard: this branch now contains his live-route commit); demo video and slides
**Blockers:** `assets_mapped.json` missing locally until `make mapping` runs
