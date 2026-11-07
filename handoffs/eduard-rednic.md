# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make api` runs on port 8001, loading the fixture or `SCENE_ASSETS`: assets, details, nearby, changes with reset, plus placeholder route and copilot (marked `placeholder: true`).
**Verified:** `make check` passes, 62 tests; route and assets checked live with curl. Changes are in memory only.
**Next:** floor map and clearance from `Equipment Room.ply`, then A*; connect Hannu's store; add TimescaleDB.
**Blockers:** Hannu's code isn't on main; his fixture uses a different format.
