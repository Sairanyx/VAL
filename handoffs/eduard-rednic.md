# eduard-rednic: eduard-height
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** on top of Viktor's `viktor/viewer-objects`: merged main keeping his routing; `/api/route` profiles are `robot` and `person`, using his height layers. Boxes only block a body if they overlap its height range.
**Verified:** `make check` passes. On `splat_v2`: 574 objects, routes to `obj-0048` for both bodies, 36 and 16 ms. The map is Viktor's shipped `nav_grid.npz`; not re-carved.
**Next:** connect Hannu's copilot to `POST /api/copilot/query` (he's ready, code on `hannu_branch`) and his store to asset details; Benjamin draws routes from `/api/route`; TimescaleDB on the 5090.
**Blockers:** PR #3 and this branch need merging with Viktor. Open: whether scene units are truly metres.
