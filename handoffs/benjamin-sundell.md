# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** phone mode (`web/phone.js`): rotate phone to look, step detection walks forward, touch joystick, Start re-centres; `make web HTTPS=1` serves HTTPS with a self-signed cert in `web/.cert/` (gitignored), needed for phone sensors. Earlier: first-person viewer (three.js 0.180 + Spark 2.4 vendored, offline), fixture boxes/labels, tap info, walk/fly, fps, URL speed settings (`?res=`, `?lod=0`, `?splats=`), `web/serve.py`, `web/make_test_scene.py`, `make web`
**Verified:** `make check` passes; HTTPS server serves the page and JS (200). Phone mode NOT tested on a real phone, and JS not run in a browser since the last change
**Next:** test phone mode on iPhone Safari (permission prompt, rotation, step sensitivity); tune STEP_HIGH/STEP_LENGTH; WebXR for Android if a teammate has one; then route line + avatar from `/api/route`
**Blockers:** the phone needs a network path to the laptop (WSL2 port forward was removed for safety); real demo uses the 5090 on the team router
