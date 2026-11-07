# viktortrilar: viktor/moving-splats
**Goal:** dragging a movable object moves the real thing in the scan, and bends the route
**Done:** app/scene/split_movable.py and `make pieces` cut chosen objects out of a scene. Viewer loads them and moves them with the drag (web/objects.js). serve.py and `make web` take `PIECES=`. Re-plans keep the route's start (web/route.js). PRs #10, #11, #12 merged: main has Valmet's scene, routes, and the Qwen copilot
**Verified:** lint; tests. Real mouse drag on a light scene with software rendering: `obj-0067` to (-1.46, -1.75), route 4.31 to 5.56 m, undo restores. Renders of the chair and cage moved 1 m look clean. Not tested: on the 5090, tablet, or the full scene in the viewer
**Next:** merge this PR. On the 5090: `make scene mapping db model pieces`, then rehearse offline. Add an "Add obstacle" button and written directions. A person confirms P-005 on obj-0049
**Blockers:** none. Cert valid to 2026-11-07 20:41. Local branch viktor/viewer-objects holds an unused merge: don't merge it
