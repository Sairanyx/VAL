# viktortrilar: viktor/copilot-llm
**Goal:** local Qwen words the copilot's answers, on checked facts, with the template as the fallback
**Done:** app/copilot/llm.py fetches facts in code, then checks the model's citations, IDs, numbers and safety. Set `COPILOT_MODEL` to turn it on. scripts/eval_copilot.py runs 20 questions. PR #10 is merged: main has Valmet's scene, routes, and copilot panel
**Verified:** lint; all tests with a fake model. Real model: 9B met 20 of 20 on 20 questions, 14 model answers, 3.6 s mean, 19.5 GB VRAM, on Roihu L40. Read by hand, it blends model confidence with the mapping in one answer. P-005 has only pressure and flow data, and nothing links it to M-005
**Next:** merge PR #11, then this PR. On the 5090: `make model`, rehearse offline, and measure memory alongside the viewer. Model answers not yet seen in the viewer
**Blockers:** none. P-005 on obj-0049 is an unconfirmed pick, confidence 0.3. Cert valid to 2026-11-07 20:41
