# benjamin-sundell: benjamin/info-buttons
**Goal:** the team's bug and fix list for the viewer, on top of main (PR #35)
**Done:** info panel buttons no longer squeeze their labels: `flex: 1 1 auto` + `white-space: nowrap`, rows wrap instead (`web/style.css`). Earlier: the fix list, merged as PR #36
**Verified:** `make check` passes. Not yet seen in a browser
**Next:** click through every fix; push and PR; tell Eduard (store.py, main.py endpoints), Viktor (plan.js, pacing default), Sasha (bim.js). Val stress test skipped (no model here). Database dummy data and demo deployment: decisions for the team
**Blockers:** none
