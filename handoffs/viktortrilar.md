# viktortrilar: viktor/laptop-demo
**Goal:** make the demo robust, clear and runnable on a judge's laptop, per the fix list
**Done:** filters (`web/filters.js`), see-through minimap, plain alerts, Focus and best view (`best_view`), five-step View (`web/views.js`), guided Demo (`web/tour.js`), worker or robot on the route (`web/avatar.js`), diagnosis on arrival, arrow keys while moving, Help panel. `make bundle` builds a zip with its own uv (`scripts/make_bundle.py`, `scripts/laptop/`). Devlog in `docs/DEVLOG.md`, brief comparison in `docs/CHALLENGE.md`
**Verified:** see the PR. Real GPU browser tests, and the zip from an empty folder on Linux
**Next:** try the zip on Windows and Mac. Rehearse offline on the demo laptop. Test the mic with a real voice. Someone else tries the new features
**Blockers:** Valmet must confirm which pump is P-005, and OK sending their data to judges by link. Sasha's dashboard isn't on GitHub: sasha_branch only holds an empty test commit. Deadline Sunday 10:00. Roihu closed until at least Monday
