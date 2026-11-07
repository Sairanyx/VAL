# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), and the tablet version of the viewer.
**Done:** merged Hannu's rotation with Viktor's collision checks, which now cover turning (`check-move` takes `yaw`). Tablet mode: tap a window to close it, no X, bigger buttons, lighter defaults. `POST /api/viewer/commands` runs any viewer action, for the voice copilot (`app/api/commands.py`, `web/commands.js`). `./start browser` and `./start tablet` run everything. Not merged: the user said to wait.
**Verified:** `make check` passes. Headless Chromium on small test scenes: 23 tablet and command checks, 10 rotation collision checks. A rotation survived an API restart in TimescaleDB. Both start commands ran. Not tested: real Lenovo, speed on the real scene.
**Next:** test on the Lenovo, then tune `?res=` and `?splats=`. 5090 and router setup; second detour; backend slide. Later, when asked: VR mode with video, telemetry simulator.
**Team:** `eduard` also contains main, Benjamin's tracking (`web/xr.js`) and Sasha's BIM mode, none of which conflict now. Hannu, rotation is here too. Not merged to main yet: the user said to wait.
**Blockers:** none.
