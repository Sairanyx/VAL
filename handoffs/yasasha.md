# yasasha: yasasha/object-highlight
**Goal:** Highlight selected scanned surfaces, not bounding boxes.
**Done:** Added app/scene/highlights.py, web/highlight.js, serving routes, selection wiring, Makefile target, tests and usage docs. Exported 440 local highlights; cut movable objects use their whole piece (cart obj-0067: 1,091 -> 31,852 splats); private data stays out of git.
**Verified:** make check: 197 passed. Chromium checked real PLY loading, movement, undo, visibility, deletion, rapid selection and missing segmentation. Actual viewer selection hid the selected box; Boxes toggle preserved the surface. Cyan rendering passed without browser errors.
**Next:** Restart viewer after make highlights; review segmentation on the full room.
**Blockers:** Fragmented objects remain separate; highlights cannot recover missing surfaces or confirm equipment identity.
