# yasasha: yasasha/bim-pick
**Goal:** Reliable selection with a hover preview, in BIM mode and in the scan; nothing behind the nearest object.
**Done:** web/bim.js picks and hovers by each element's simple Box shape in every look (Real, Mesh, Box); faint shell and outline on hover, pointer cursor; web/main.js checks the mouse once a frame. Scan view hovers the object a click would pick, outlined with its BIM simple shape (web/hover.js, shared). docs/USAGE.md.
**Verified:** make check 252 passed. Chromium on real data: rays through three bucket centres miss the scan mesh but pick the bucket in all looks; a real mouse hover and click picked bucket obj-0148; hover clears on empty space and leaving the canvas. Scan hover: bucket outline matches the clicked object; outline follows a moved cart; BIM on/off swaps cleanly. web/pick.js: nearest object wins, pipes block only at their scanned surface; 120 rays at the cart picked nothing behind it (old rule: 51).
**Next:** Check hover speed on the GPU machine; tablet has no hover, taps use the same shapes.
**Blockers:** none. BIM Real/Mesh/Box merged in #28.
