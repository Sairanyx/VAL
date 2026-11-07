# yasasha: yasasha/bim
**Goal:** BIM mode: a simulated, interactive BIM model of the room, plus an IFC export.
**Done:** app/bim/ (room walls from scan density, IFC4 writer with no new dependency, bim.json), web/bim.js (BIM button, class filters, IFC properties, isolate, section cut, IFC download; moves and routes still work), `make bim`, `--bim` in serve.py, docs/USAGE.md.
**Verified:** make check; tests/test_bim.py with IfcOpenShell: 0 schema issues on real model.ifc, 445 elements, geometry placed correctly. Chromium: enter/exit, tap P-005 (IfcPump), move follows, section, isolate, download.
**Next:** Thin pipe shapes instead of bounding boxes; doors/openings; rebuild after operator edits.
**Blockers:** none. Earlier: surface highlights merged in #19.
