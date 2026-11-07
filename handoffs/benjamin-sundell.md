# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** phones/tablets load the light scene automatically: `make web` passes `--light $(SCENE_DIR)/light_full.ply` when it exists (not with PIECES, since that copy still has the cut-out objects); serve.py serves it at `/scene-light.ply`; main.js picks it on touch devices, `?scene=full|light` overrides, status shows which. Earlier: route arrows (merged in PR #21)
**Verified:** `make check` passes (215); `make -n web` adds `--light` for the equipment_room scene and leaves it out with PIECES. Not yet tried on a phone/tablet
**Next:** try on a tablet with up-to-date Chrome (89+; the test tablet had Chrome 81); then render-on-demand, label throttling, merged boxes for phone fps
**Blockers:** test tablet's Chrome 81 can't run the viewer (no import maps)
