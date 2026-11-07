# viktortrilar: viktor/laptop-demo
**Goal:** make the demo robust, clear and runnable on a judge's laptop, per the fix list
**Done:** filters (`web/filters.js`), see-through minimap, plain alerts, Focus and best view (`best_view`), five-step View (`web/views.js`), guided Demo (`web/tour.js`), worker or robot on the route (`web/avatar.js`), diagnosis on arrival, arrow keys while moving, Help panel. `make bundle` builds a zip with its own uv (`scripts/make_bundle.py`, `scripts/laptop/`). Merged Sasha's dashboard. Labels show status and health. Devlog in `docs/DEVLOG.md`, brief comparison in `docs/CHALLENGE.md`
**Verified:** 413 tests, lint. Real GPU browser checks: 17 tour, 9 walk, 42 filters and minimap, 20 of 22 keys (2 refused turns), 28 combine, 13 naming, 11 polish, 18 split and filters. The zip from an empty folder on Linux: first run 19 s, tour 17 of 17
**Next:** try the zip on Windows and Mac. Rehearse offline on the demo laptop. Test the mic with a real voice. Someone else tries the new features
**Blockers:** Valmet must confirm which pump is P-005, and OK sending their data to judges by link. Deadline Sunday 10:00. Roihu closed until at least Monday
