# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make api` on port 8001 from the fixture or `SCENE_ASSETS`, with placeholder route and copilot; `make floor SCENE=...` builds the map with clearance per body size (`app/nav/grid.py`).
**Verified:** `make check` passes. Floor on `Equipment Room.ply`: 33.8 m2 free, 7.6 m2 connected at 0.6 m wide. Not checked against views.
**Next:** A* with body sizes on the grid, wire into `/api/route`, check the route reaches `P-005`; then Hannu's store and TimescaleDB.
**Decided:** TimescaleDB on the 5090 and in the cloud; tablets talk only to the 5090; the 5090 syncs to the cloud when it can.
**Blockers:** which object is `P-005`; Hannu's code isn't on main and his fixture format differs.
