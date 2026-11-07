# eduard-rednic: eduard_main
**Goal:** finish Val and let people talk to it, offline, after swapping test parts with Hannu. Stays on this branch for now, not in main.
**Done:** mic with offline speech (`app/copilot/voice.py`, `web/voice.js`, `make voice-model`). Val runs view actions from speech or typing (`app/copilot/viewer_actions.py`). New safety rules (`guardrails_patterns.py`), "I don't understand" reply, "Make path" name, read aloud removed, 60-question test (`scripts/eval_copilot.py`). `./start tablet` now uses https, as the mic needs it.
**Verified:** `make check`: 352 passed. Chromium with spoken test audio as a fake mic: 7 of 7, including https on the tablet layout. Every action run in the browser. 56 of 60 in the Val test, and the other 4 fell back to the records.
**Not verified:** a real voice, the tablet's mic, a noisy room. Nobody has scored the 60 answers by hand yet.
**Next:** try the mic by voice, then score the 60. Later: 5090 `make db` and `make api`, router and offline network.
**Team:** Hannu, I changed your safety rule, so please check `app/copilot/guardrails_patterns.py`. Run `make voice-model` once before going offline. `av` is pinned below 16, as faster-whisper breaks on newer versions.
**Blockers:** none.
