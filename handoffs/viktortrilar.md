# viktortrilar: viktor/moving-splats
**Goal:** close the limits on moving objects and on testing everything together
**Done:** app/scene/movable_members.py cuts by masks. Four checked objects move as real splats (roll cage by box; chairs obj-0021, obj-0008 and box obj-0112 by masks), others as outlines. Add object, floor patch, Range limit (at most 15 frames, 8 labels), and a "?" on procedural links. members.npz is in Release objects-v2
**Verified:** lint; tests. Full flow in a headless browser with the template copilot: route, copilot, refusal, drag to 5.56 m, add, undo, no page errors. Real Qwen 9B through the API on Roihu: checked answers in about 3 s, refusal, label suggestion. Full scene loads in the viewer with no errors, at 1 fps in software. By eye, only 3 of 25 high-scoring mask cuts look clean
**Not tested:** 5090, tablet, real frame rate, model text shown in the browser (compute node login refused the tunnel)
**Next:** merge PR #13 and rehearse on the 5090. Then a per-scene config and `make pipeline`: the full job is still only in scratch. A second room would prove transfer
**Blockers:** none. P-005 on obj-0049 is an unconfirmed pick. Cert valid to 2026-11-07 20:41
