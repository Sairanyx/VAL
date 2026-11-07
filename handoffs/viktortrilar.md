# viktortrilar: main (viktor/numbers merged)
**Goal:** demo on Valmet's uncleaned scene, then measure and improve the scored numbers
**Done:** route check, `make pipeline`, per-scene config, configurable copilot default. Docs updated: tasks and demo steps are in docs/PLAN.md under "Now"
**Verified:** lint; 189 tests passed, 2 skipped. 383 of 384 routes touch fewer than 10 splats. `make pipeline` has only had a dry run. Not tested: 5090, tablet, model text in the browser panel
**Next:** rehearse on the 5090. Ask Valmet which pump is P-005. When CSC returns: 60-object precision sample, label review, grouping check, second pass, real pipeline run. Write the 60-question copilot test
**Blockers:** SSH to Roihu, Puhti and Mahti times out from two networks, no maintenance announced. Use `ssh -4` on networks without IPv6. Cert valid to 2026-11-07 20:41. Local branch viktor/viewer-objects holds an unused merge: don't merge it
