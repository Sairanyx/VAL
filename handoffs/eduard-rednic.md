# eduard-rednic: eduard-context
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md under "Now".
**Done:** merged API, TimescaleDB, Excel links and `make nav-check` (PRs #1-#9). Viktor has since moved the demo to the uncleaned `Equipment Room.ply`, with `P-005` on `obj-0049` (unconfirmed).
**Verified:** `make check` on main passes, 191 tests. `make db` and `make api` haven't been run on the 5090.
**Next:** set up `make db` and `make api` on the 5090, plus the router and offline network; find a second good detour; backend slide. Later, when asked: telemetry simulator for diagnostics.
**Blockers:** none. CSC SSH is down, which affects Viktor and Sasha, not this work.
