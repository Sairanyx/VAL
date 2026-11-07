# eduard-rednic: eduard-live-route
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** the route now updates live: re-planned every 0.1 m while walking around, and while dragging an object using a `preview` on `POST /api/route`, which saves nothing. Auto-walk trims the line behind you (`web/route.js`, `web/main.js`, `app/api/main.py`).
**Verified:** `make check` passes; route logic tested in Node with a fake backend. Not yet run in a real browser or on the 5090.
**Next:** check the route in the 3D scene once Benjamin draws it; rehearse on the 5090 offline. Later, when asked: telemetry simulator.
**Team:** viewer should use `data/scene/equipment_room/light_full.ply` and `assets_mapped.json`, which now has different object IDs from `splat_v2`.
**Blockers:** none. Open: `obj-0046` is a test pick for `P-005`, and needs a person to confirm it; the `start` point `[0, 1.178, 0]` is only the scene's default.
