# yasasha: yasasha/bim-pick
**Goal:** Reliable BIM selection: tapping a gap in a scanned object still picks it, with a hover preview.
**Done:** web/bim.js picks and hovers by each element's simple Box shape in every look (Real, Mesh, Box); faint shell and outline on hover, pointer cursor; web/main.js checks the mouse once a frame. docs/USAGE.md.
**Verified:** make check 252 passed. Chromium on real data: rays through three bucket centres miss the scan mesh but pick the bucket in all looks; a real mouse hover and click picked bucket obj-0148; hover clears on empty space and leaving the canvas.
**Next:** Check hover speed on the GPU machine; tablet has no hover, taps use the same shapes.
**Blockers:** none. BIM Real/Mesh/Box merged in #28.
