# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** phone UI fixes: info window no longer closes right after tapping an object (browser's ghost click after the tap landed on the new window; windows now ignore clicks for 500 ms after a scene tap, in main.js); buttons are one sideways-scrolling row at the bottom on touch devices and wrap on narrow desktop windows; joystick sits above the row; windows scroll inside themselves; move/rotate bar wraps and hides the joystick (style.css). Earlier: Track (WebXR), one tablet mode, route arrows
**Verified:** `make check` passes (227). UI fixes not yet seen on a phone
**Next:** test Track on an ARCore Android device over HTTPS; check scale (are scene units metres?) by walking a known distance; then render-on-demand and label throttling for phone fps
**Blockers:** test tablet's Chrome 81 can't run the viewer (no import maps)
