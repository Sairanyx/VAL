# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make api` on port 8001. PR #1 merged. PR #2 adds real A* with body sizes in `/api/route`, used when `NAV_GRID` or the default `nav_grid.npz` exists; otherwise the marked placeholder.
**Verified:** `make check` passes. A* takes under 20 ms on the real map. Not yet run against real objects; floor not checked against views.
**Next:** load `assets_final.json`, pick a reachable `P-005`; object footprints for moves; TimescaleDB.
**Decided:** no cloud: TimescaleDB runs on the local 5090, and tablets talk only to it.
**Blockers:** `assets_final.json` and the `P-005` choice from Viktor; Hannu's code isn't on main and his fixture format differs.
