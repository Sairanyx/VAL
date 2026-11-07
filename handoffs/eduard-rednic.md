# eduard-rednic: eduard_main
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md under "Now".
**Done:** my work is on main through Viktor's PR #30: API, TimescaleDB, Excel links, `make nav-check`, tablet mode, viewer commands, `./start`, rotation with collisions, and the move and save fixes. `eduard_main` follows main. Added `docs/ARCHITECTURE.md` and `docs/TEST_CHECKLIST.md`.
**Verified:** the architecture was checked against `scripts/pipeline.py`, the Makefile and `docs/PLAN.md`. Docs only, so no tests were needed. The copilot answers through the API with fixed answers. Not tested on main myself: the viewer, 0.8B model, spoken answers.
**Next:** set up `make db` and `make api` on the 5090, plus the router and offline network; second detour; backend slide. Later, when asked: telemetry simulator, VR mode with video.
**Team:** leaving PR #31 alone, as asked. `eduard` and `eduard-clean` are old backups, so don't merge them. On this laptop, use `MODEL=Qwen3.5-0.8B`: 4B doesn't fit the GPU.
**Blockers:** none.
