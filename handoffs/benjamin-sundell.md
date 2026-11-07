# benjamin-sundell: benjamin/object-list
**Goal:** the team's bug and fix list for the viewer, on top of main (PR #35)
**Done:** Objects side panel (`web/objectlist.js`, button "Objects", key L, Esc closes): equipment with an Excel condition, most important first (state, urgency, criticality, lowest health), health bar, issue; sort by importance/health/name, search, optional objects without a record; tap a row to select and open its details. Uses `condition` from `/api/assets`. Earlier: fix list (PR #36), info buttons (PR #37)
**Verified:** `make check` passes (275 passed, 4 skipped). Checked the data: 30 linked objects, states attention_required 3, degraded 6, watch 4, healthy 17. Panel not yet seen in a browser
**Next:** click through every fix; push and PR; tell Eduard (store.py, main.py endpoints), Viktor (plan.js, pacing default), Sasha (bim.js). Val stress test skipped (no model here). Database dummy data and demo deployment: decisions for the team
**Blockers:** none
