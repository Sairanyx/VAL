# eduard-rednic: eduard-mapping
**Goal:** floor, routing, nearby search and backend API (`app/nav/`, `app/api/`), per docs/PLAN.md.
**Done:** `make mapping` links all 30 Excel records to objects by class (`app/copilot/mapping.py`), writing `mapping.json` and `assets_mapped.json`. Run the API with `SCENE_ASSETS=data/scene/splat_v2/assets_mapped.json`. PR #4 merged with Viktor's and Hannu's work.
**Verified:** `make check` passes; live results in the PR. Links are procedural, not real identities.
**Next:** viewer uses `assets_mapped.json` (Benjamin); TimescaleDB on the 5090; changes are still in memory.
**Blockers:** none. Open: scene units; a person confirming `P-005`; 544 objects have no Excel record because there are only 30 records.
