# viktortrilar: viktor/copilot-llm
**Goal:** local Qwen words the copilot's answers, on checked facts, with the template as the fallback
**Done:** app/copilot/llm.py fetches facts in code, then checks the model's citations, IDs, numbers and safety. Set `COPILOT_MODEL` to turn it on. scripts/eval_copilot.py runs 20 questions. PR #10 is merged: main has Valmet's scene, routes, and copilot panel
**Verified:** lint passes; 157 tests pass, 2 skipped, using a fake model. Real model not yet measured: job 2927176 running, 4B and 9B, answers in `sinceai/runs/llm`
**Next:** read the saved answers, not only the counts. Pick a model or keep the template. pyproject needs transformers 5+ and a way to fetch weights, in their own small PR. Then rehearse on the 5090 and a tablet, offline
**Blockers:** none. P-005 on obj-0049 is an unconfirmed pick, confidence 0.3. Cert valid to 2026-11-07 20:41
