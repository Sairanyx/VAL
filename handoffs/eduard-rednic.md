# eduard-rednic: eduard
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md under "Now".
**Done:** merged live route updates: re-plans every 0.1 m, or at most every 50 ms, while moving or dragging (`preview` on `POST /api/route` saves nothing). Earlier: API, TimescaleDB (`make db`), Excel links (`make mapping`), `make nav-check`. Old `eduard-*` branches deleted; use `eduard`.
**Verified:** `make check` passes on main. Live updates passed 14 Node checks with a fake backend and API speed tests. Not yet run in a real browser or on the 5090.
**Next:** set up `make db` and `make api` on the 5090, plus the router and offline network; find a second good detour; backend slide. Later, when asked: telemetry simulator for diagnostics.
**Team:** Benjamin's arrows branch contains my live-route commit, which is now on main, so merge main first. Viktor's PR #18 changes moves: check that drag previews still work with it. Hannu's copilot rules are his to change.
**Blockers:** none. Open: which pump is `P-005` (`obj-0049` is unconfirmed), and a real start point.
