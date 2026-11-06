# viktortrilar: main (uncommitted)
**Goal:** team workflow and agent guidelines, before the challenge is announced
**Done:** added AGENTS.md, CLAUDE.md, handoffs/, .env.example, tests/test_smoke.py, CI (.github/workflows/check.yml), .claude/settings.json + handoff_check.sh, make lint/test/check, ruff rules, pytest
**Verified:** ruff format, ruff check and pytest pass with dev tools only (1 passed, 1 torch test skipped); hook tested by hand. Not run: `make test` with torch, CI on GitHub, hook in a live session
**Next:** review, move to a branch, commit, open a PR; fill in team areas in AGENTS.md
**Blockers:** none
