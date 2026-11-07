# viktortrilar: viktor/move-collisions
**Goal:** demo on Valmet's uncleaned scene, then measure and improve the scored numbers
**Done:** app/api/collisions.py refuses moves onto other objects, walls, or fixed equipment, in the backend and live in the viewer: red box, red panel, back to the last good spot. Boxes are loose, so only moves that make things worse than the start are refused
**Verified:** lint; all tests. Browser: drag onto a cart goes red and returns to the last good spot, saved on both sides; demo move still gives 4.31 to 5.56 m; undo restores; direct API call gets 409. Not tested: 5090, tablet
**Next:** rehearse on the 5090. Ask Valmet which pump is P-005. When CSC returns: 60-object precision sample, label review, grouping check, second pass, real pipeline run. Write the 60-question copilot test
**Blockers:** SSH to Roihu, Puhti and Mahti times out from two networks, no maintenance announced. Use `ssh -4` on networks without IPv6. Cert valid to 2026-11-07 20:41. Local branch viktor/viewer-objects holds an unused merge: don't merge it
