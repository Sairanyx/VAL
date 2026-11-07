# benjamin-sundell: benjamin/webviewer
**Goal:** web viewer for the tablet demo (`web/`), per docs/PLAN.md
**Done:** "Track" button (`web/xr.js`): WebXR + ARCore track the device on Android Chrome and the whole map moves with it via an `xrOffset` group above `root` (main.js); start point and facing calibrate on start, Start re-calibrates; map drawn opaque; other controls off while tracking. Button only shows where immersive-ar is supported (HTTPS). Earlier: one tablet mode (Eduard's TABLET flag + light scene)
**Verified:** `make check` passes. Tracking NOT tested: needs an ARCore Android device with Chrome 89+, so Spark rendering inside WebXR is unverified
**Next:** test Track on an ARCore Android device over HTTPS; check scale (are scene units metres?) by walking a known distance; then render-on-demand and label throttling for phone fps
**Blockers:** test tablet's Chrome 81 can't run the viewer (no import maps)
