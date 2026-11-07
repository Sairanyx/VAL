# yasasha: yasasha/bim
**Goal:** BIM mode: a simulated, interactive BIM model of the room close to the real objects, plus IFC.
**Done:** app/bim/ (room from scan density; per-object scan meshes and true-colour splats in shapes.py and __main__.py; IFC4 with triangulated meshes), web/bim.js (BIM button, Real/Model look, class filters, IFC properties, isolate, section, IFC download; moves follow), `make bim`, serve.py `--bim`, docs/USAGE.md.
**Verified:** make check 223 passed. IfcOpenShell on real model.ifc: 0 schema issues, 445 elements built. Chromium (software GL): enter/exit, P-005 picked via its mesh, cart mesh and splats follow a move, section, isolate, download.
**Next:** Check frame rate on a real GPU and tablet; merge partial detections (pallet jack) for fuller shapes.
**Blockers:** none. web/ is Benjamin's area: ask him before merging.
