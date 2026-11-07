# viktortrilar: viktor/copilot-llm
**Goal:** local Qwen words the copilot's answers, on checked facts, with the template as the fallback
**Done:** app/copilot/llm.py fetches facts in code, then checks the model's citations, IDs, numbers and safety. Set `COPILOT_MODEL` to turn it on. scripts/eval_copilot.py runs 20 questions. PR #10 is merged: main has Valmet's scene, routes, and copilot panel
**Verified:** lint passes; 14 model-layer tests pass with a fake model. First real run, 20 questions: 9B 19 of 20 met, about 3 s each, 19.4 GB VRAM; 4B 13 of 20, 9.6 GB, and it called health 44 "high". P-005 has only pressure and flow data, and nothing links it to M-005. Retest: 20 of 20 met, 14 model answers
**Next:** read the last 9B run (job 2927205, `sinceai/runs/llm`), then open the PR. PR #11 updates transformers. On the 5090: `make model`, then rehearse offline, and measure memory alongside the viewer
**Blockers:** none. P-005 on obj-0049 is an unconfirmed pick, confidence 0.3. Cert valid to 2026-11-07 20:41
