# eduard-rednic: eduard-nav-tools
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make nav-check` tests floor, routes, mapping and API together. `make floor VIEWS=...` keeps floater removal and writes `nav_grid_new.npz`. If the database drops, changes stay in memory and save once it's back (`saved`, `unsaved_changes`).
**Verified:** `make check` passes; nav-check 12 of 12; database stop and start tested live. `make floor` not run for real, as the views are on Roihu; the shipped map doesn't need rebuilding.
**Next:** check the route in the 3D scene once Benjamin draws it; rehearse on the 5090 offline. Later, when asked: telemetry simulator for diagnostics.
**Decided:** scene is in metres. Leave Hannu's rules to him.
**Blockers:** none. Open: a person confirming `P-005`.
