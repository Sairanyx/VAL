# Using Entire

Entire records agent sessions alongside Git commits, so teammates can pick up work, and adds a code
graph to cut token use. It's for the optional "Best Use of Entire" prize. It isn't part of the demo,
so it doesn't affect the on-site rule.

## Setup
```bash
git pull
make entire                  # for Claude Code
make entire AGENT=codex      # for another agent. `entire agent` lists the options
```
This installs Entire 0.13.1 to `~/.local/bin`, sets up its hooks, and adds the code graph. It's safe
to re-run. Git commit hooks are per clone, so everyone runs it once. No account was needed in testing.

If you skip it, Claude Code hooks do nothing and work carries on as normal.

## Privacy
- **Transcripts sync to this repo on `git push`.** That includes prompts and agent output.
- **Never paste secrets.** Redaction is a safety net, not a guarantee.
- **Before making this repo public,** for example for submission, ask the team and check what to
  remove. Anyone who can read the repo can read its checkpoints. Consider submitting a clean copy.

## Daily use
| Task | Command |
|---|---|
| Find code | `entire graph query --repo . --profile full --head --query "..."` |
| Check what a change affects | `entire graph impact --repo . --head --symbol NAME` |
| Pick up a teammate's session | `entire session resume BRANCH` |
| Read a checkpoint | `entire checkpoint explain ID` |
| See what would be pushed | `entire checkpoint list --outgoing` |
| Check token use | `entire tokens` |
| Estimate graph savings | `entire graph stats` |

Avoid `entire session resume BRANCH --force`, because it may reset your Git state.

Keep updating `handoffs/`, so nobody depends on Entire to take over work. Record token use from the
start, as the prize looks for measurable savings. Add those numbers to `docs/RESULTS.md`.

## Optional, if time allows
- **Brain:** `entire plugin install brain`, then `entire brain setup`. It stores project knowledge,
  but its memory extraction can use tokens.
- **Trails:** task and review tracking. It needs the repo mirrored on Entire, with Entire's GitHub
  App installed, so the repo owner has to do that.

## Not yet confirmed
- A real session's transcript reaching GitHub, and a teammate resuming it.
- Whether agents other than Claude Code behave the same way.
