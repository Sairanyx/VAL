# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** merged Eduard's `eduard` branch (tablet mode, rotation, viewer commands) into mine and kept one tablet mode: his `TABLET` flag (touch screens, `?tablet=1|0`) now also loads `light_full.ply` via my `pickScene` (`?scene=full|light` overrides). Removed my separate TOUCH check. docs/USAGE.md updated
**Verified:** `make check` passes (225). Not tried on a device
**Next:** try on a tablet with up-to-date Chrome (89+; the test tablet had Chrome 81); then render-on-demand, label throttling, merged boxes for phone fps
**Blockers:** test tablet's Chrome 81 can't run the viewer (no import maps)
