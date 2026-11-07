# eduard-rednic: eduard-original-scene
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** switched the defaults to the original `Equipment Room.ply`, as ours has holes in the floor. `make scene` gets `objects-v1`; then `make floor mapping db api`. `/api/assets` returns `start`. All 30 Excel records link to objects.
**Verified:** `make check` passes; `make nav-check` 12 of 12; live API on the scene. Target is `obj-0046`, person route 3.17 m, stops 1.25 m away.
**Next:** check the route in the 3D scene once Benjamin draws it; rehearse on the 5090 offline. Later, when asked: telemetry simulator.
**Team:** viewer should use `data/scene/equipment_room/light_full.ply` and `assets_mapped.json`, which now has different object IDs from `splat_v2`.
**Blockers:** none. Open: `obj-0046` is a test pick for `P-005`, and needs a person to confirm it; the `start` point `[0, 1.178, 0]` is only the scene's default.
