# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), and the tablet version of the viewer.
**Done:** merged Hannu's rotation with Viktor's collision checks, which now cover turning (`check-move` takes `yaw`). Tablet mode: tap a window to close it, no X, bigger buttons, lighter defaults. `POST /api/viewer/commands` runs any viewer action, for the voice copilot (`app/api/commands.py`, `web/commands.js`). Not merged: the user said to wait.
**Verified:** `make check` passes. 23 checks in headless Chromium with touch, on a tiny test scene with no floor map. Not tested: real Lenovo, the real scene's speed, dragging to rotate into another object in the browser.
**Next:** test on the Lenovo, then tune `?res=` and `?splats=`. 5090 and router setup; second detour; backend slide. Later, when asked: VR mode with video, telemetry simulator.
**Team:** Hannu, rotation is here on top of your commit, so continue from `eduard` or wait for the merge. Benjamin, `web/` changed: tablet mode and `commands.js`.
**Blockers:** none.
