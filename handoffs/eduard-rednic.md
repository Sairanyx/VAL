# eduard-rednic: eduard-timescale
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make db` starts local TimescaleDB and loads Excel telemetry (`app/api/db.py`). Scene changes survive a restart, asset details read telemetry from the database, and `GET /api/health` shows what's connected. `add_telemetry` takes a `source`, ready for simulated data.
**Verified:** `make check` passes, 135 tests. Live: 4,320 rows, move survives restart, reset clears it, API runs with the database stopped.
**Next:** simulated machine data and diagnostics; viewer uses `assets_mapped.json` and draws routes (Benjamin).
**Hannu:** the copilot still reads telemetry from Excel, so simulated data needs his side too. Leave his rules to him.
**Blockers:** none. Open: if the database drops while the API runs, saving a change errors; whether self-hosted counts for the Tiger Data prize; scene units; a person confirming `P-005`.
