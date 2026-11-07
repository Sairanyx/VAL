# viktortrilar: viktor/merge-all
**Goal:** get every branch's work onto main, then make the viewer faster and simpler and work on the copilot, Val, after the engineer's feedback
**Done:** merged `eduard` (tablet mode, viewer commands, rotation, start commands, spoken answers, which includes `hannu_branch`), `benjamin/webviewer` (phone fixes, automatic light scene, tracking) and `yasasha/extract` (unused SAM3 route). BIM objects now turn around their centres. Done no longer claims Saved
**Verified:** 229 tests passed, 20 skipped, lint clean. Headless browser on merged code: 66 of 66 route checks, Plan, move, DXF and IFC downloads, BIM mode, no page errors. Not tested: turning an object in BIM mode, 5090, tablet or touch, real tracking
**Next:** viewer speed, a simpler UI (16 buttons show at once), rename the copilot to Val and improve it
**Blockers:** live IFC download has boxes only (0.9 MB), while `make bim`'s file has scan meshes (13 MB). A moved object's old spot can stay blocked. `make api` restarts on any `.py` edit in the repo. Left unmerged on purpose: `sasha_branch` (empty test commit), `viktor/viewer-objects` (old merge with no work of its own)
