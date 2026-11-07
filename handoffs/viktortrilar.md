# viktortrilar: viktor/fix-copilot-button
**Goal:** get every branch's work onto main, then make the viewer faster and simpler and work on the copilot, Val, after the engineer's feedback
**Done:** the Copilot and Ask copilot buttons work again. They broke when `web/copilot.js` and `web/main.js` got out of step, on main since #30. Before that: merged `eduard`, `benjamin/webviewer` and `yasasha/extract`
**Verified:** headless browser with the Excel data: the button opens the panel, a typed question and Ask copilot both get real answers, no page errors. Not tested: the local model, 5090, tablet
**Next:** viewer speed, a simpler UI (16 buttons show at once), rename the copilot to Val and improve it
**Blockers:** live IFC download has boxes only (0.9 MB), while `make bim`'s file has scan meshes (13 MB). A moved object's old spot can stay blocked. `make api` restarts on any `.py` edit in the repo. Left unmerged on purpose: `sasha_branch` (empty test commit), `viktor/viewer-objects` (old merge with no work of its own)
