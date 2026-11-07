# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** merged main (BIM mode, Plan screen, DXF) into this branch, keeping Eduard's tablet mode/rotation/commands and my Track, light scene, phone UI fixes alongside it (conflicts in main.js, style.css, index.html, highlight.js, Makefile, app/api/main.py). Before that: phone UI fixes: info window no longer closes right after tapping an object (browser's ghost click after the tap landed on the new window; windows now ignore clicks for 500 ms after a scene tap, in main.js); buttons are one sideways-scrolling row at the bottom on touch devices and wrap on narrow desktop windows; joystick sits above the row; windows scroll inside themselves; move/rotate bar wraps and hides the joystick (style.css). Earlier: Track (WebXR), one tablet mode, route arrows
**Verified:** `make check` passes (240 passed, 3 skipped). Merged viewer not yet opened in a browser
**Next:** open a PR to main (no conflicts now); check BIM + rotation + tablet layout together in the browser; test Track on an ARCore device
**Blockers:** test tablet's Chrome 81 can't run the viewer (no import maps)
