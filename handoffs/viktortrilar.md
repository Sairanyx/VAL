# viktortrilar: viktor/numbers
**Goal:** measure and improve the scored numbers, and automate the pipeline
**Done:** PR #13 merged. scripts/check_routes.py checks every route against splats. scripts/pipeline.py, scenes/equipment_room.toml and `make pipeline` run a scene from one config. Viewer reads the fault tag and up direction from the assets file
**Verified:** lint; tests. 383 of 384 routes touch fewer than 10 splats. Pipeline dry run only: no real run yet, because Roihu is unreachable (network unreachable on port 22)
**Next:** when Roihu returns: 60-object precision sample, review ungraded objects, merge fragments and pipe runs, second pass for unframed splats, bigger copilot test, real pipeline run
**Blockers:** Roihu unreachable from this network. Cert valid to 2026-11-07 20:41. Set COPILOT_FAULT_TAG for another site
