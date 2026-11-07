# eduard-rednic: eduard-height
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** merged Viktor's PR #3 work and Hannu's copilot with main. `app/api/copilot_link.py` connects `/api/copilot/query` and asset details to the Excel store. Routes use `robot` or `person`. `/` redirects to `/docs`.
**Verified:** `make check` passes. Live on `splat_v2` with the Excel pack: `P-005` diagnosis, service history, route, nearby. Excel pack goes in `data/`.
**Next:** only `obj-0048` has an Excel record, so map more objects (Hannu, 30% score); Benjamin draws routes; TimescaleDB on the 5090; changes are still in memory.
**Decided:** `fixtures/sample_assets.json` uses the real `assets.json` format. Hannu's old fixture is `fixtures/copilot_assets.json`, for his tests only.
**Blockers:** none. Open: whether scene units are truly metres; a person confirming `P-005`.
