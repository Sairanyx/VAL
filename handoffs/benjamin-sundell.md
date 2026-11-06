# benjamin-sundell: benjamin/viewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** first-person "camera feed" viewer: three.js 0.180 + Spark 2.4 vendored in `web/vendor/` (offline), splat + fixture boxes coloured by status (P-005 red), on-screen labels for objects in view with distance, crosshair "looking at", tap for info panel, walk/fly toggle, fps counter (`web/main.js`, `index.html`, `style.css`). `web/serve.py` (stdlib server, `/scene.ply` + `/assets.json`), `web/make_test_scene.py` (fake splat from the fixture), `make web`
**Verified:** `make check` passes; every file is served with 200; headless Chrome loads the page, the fixture and the 31k-splat test scene with no JS errors, and draws the boxes. Splats didn't show in headless screenshots (timing/WebGL), so not yet seen rendered in a real browser
**Next:** open in a desktop browser and confirm splats render; get `Equipment Room.ply` from Viktor and test on a real tablet (fps, memory); try a reduced scene if slow; then route line + avatar from `/api/route`
**Blockers:** need `Equipment Room.ply`; WSL2 may need port forwarding or mirrored networking for a tablet to reach it
