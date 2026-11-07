# eduard-rednic: eduard_main
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md under "Now".
**Done:** my work is on main: API, TimescaleDB, Excel links, `make nav-check`, tablet mode, viewer commands, `./start`, rotation with collisions, move and save fixes, `docs/ARCHITECTURE.md`. Remade `docs/TEST_CHECKLIST.md`: features, status, keep or cut, every deliverable, and who tests each part.
**Verified:** `make check` passes on main, 267 tests. The checklist's statuses come from teammates' handoffs and the code, and no box is ticked: a person has to test on the real scene. Docs only since then.
**Next:** set up `make db` and `make api` on the 5090, plus the router and offline network; second detour; backend slide; old spot staying blocked after a move. Later, when asked: telemetry simulator, VR mode with video.
**Team:** everyone, please tick `docs/TEST_CHECKLIST.md`. `eduard` and `eduard-clean` are old backups, so don't merge them. On this laptop, use `./start laptop` or `MODEL=Qwen3.5-0.8B`: 4B doesn't fit the GPU.
**Blockers:** none.
