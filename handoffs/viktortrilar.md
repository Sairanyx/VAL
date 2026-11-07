# viktortrilar: viktor/move-sync
**Goal:** demo on Valmet's uncleaned scene, then measure and improve the scored numbers
**Done:** viewer restores saved moves after a reload, ends a drag released outside the canvas, and warns when the backend is off or has different objects. docs/USAGE.md explains setup, moving objects step by step, and fixes. Tasks and demo steps are in docs/PLAN.md under "Now"
**Verified:** lint; browser tests of no backend, wrong files, drag, release over a button, reload, fixed objects, undo, on a light scene with software rendering. Not tested: 5090, tablet, model text in the browser panel, `make pipeline` beyond a dry run
**Next:** rehearse on the 5090. Ask Valmet which pump is P-005. When CSC returns: 60-object precision sample, label review, grouping check, second pass, real pipeline run. Write the 60-question copilot test
**Blockers:** SSH to Roihu, Puhti and Mahti times out from two networks, no maintenance announced. Use `ssh -4` on networks without IPv6. Cert valid to 2026-11-07 20:41. Local branch viktor/viewer-objects holds an unused merge: don't merge it
