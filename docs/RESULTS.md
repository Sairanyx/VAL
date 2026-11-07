# Results

One line for each run worth keeping. Raw outputs stay in `runs/` or on Roihu, not in git. These
numbers feed the scene comparison, slides, and technical note, so only record what was measured.

## Scenes
| Check | `Equipment Room.ply` | Own splat |
|---|---|---|
| Assets framed | Not run | Not built |
| Junk boxes, out of 30 sampled | Not run | Not built |
| Route reaches `P-005` candidate without clipping | Not compared on one object | `obj-0048`: 6.8 m at 0.6 m wide, looks clear in 7 rendered views along the route |
| Floor area connected at 0.6 m wide (Valmet with movable objects and low clutter left out) | 7.4 m2 | 0.2 m2 without floater removal, 6.6 m2 with it. Equal settings not compared |
| Held-out views, 40 frames, against real photos (Valmet aligned by ICP, which may lower its score) | 11.82 dB | 26.57 dB, and clearly better by eye |

## Runs
| Date | Owner | Step | Scene or input | Settings | Result | Time | Peak memory | Machine |
|---|---|---|---|---|---|---|---|---|
| 2026-11-06 | Viktor | Validate PLY | `Equipment Room.ply` | | 1,676,481 of 1,676,481 records valid | | | ThinkPad |
| 2026-11-06 | Viktor | Clean scene | `Equipment Room.ply` | Opacity above 0.05, floater removal | 1,178,554 splats kept, floor y about 1.18 | About 4 s | 0.8 GB RAM | ThinkPad |
| 2026-11-06 | Viktor | Render views | Cleaned `Equipment Room.ply` | 1280x720, 75 degree FOV, 2 heights | 400 views, 129 rejected, 92% depth coverage, 93% of depth points within about 10 cm of solid splats (sample of 12 views) | 8.8 s | 0.7 GB VRAM | Roihu L40 |
| 2026-11-06 | Viktor | Render detail views | Cleaned `Equipment Room.ply` | 1280x720, 50 degree FOV, 3 heights, tilts of -30, 0, 30 | 300 views, floor-heavy views filtered. With the first 400, solid splats seen at over 400 px per unit by 3+ views rose from 70.5% to 87.2%, upper room 35.6% to 68.6% | 14.2 s | Not re-measured, 0.6 GB VRAM before the filter | Roihu L40 |
| 2026-11-07 | Viktor | Rough 3D clustering | Cleaned `Equipment Room.ply` | 0.03 voxels, opacity above 0.5, at least 200 splats | 195 unnamed objects, 25% of splats. Recognizable carts, tanks, racks; touching things merge | About 1.5 s | 0.5 GB RAM | ThinkPad |
| 2026-11-07 | Viktor | Lighter scene, PSNR against full render on 20 views | Cleaned `Equipment Room.ply` | Base color only | All splats: 66 MB, 28.6 dB, looks close. 400k random, enlarged: 22 MB, 21.7 dB, soft. 400k most visible: 19.3 dB | | | Roihu L40 |
| 2026-11-07 | Viktor | SAM 3 + SAM 2 masks (VLSplat preprocess) | 20 rendered views | Industrial text prompts | 36-107 masks per view, 63-90% pixels covered, clean outlines. Labels weak: 49% "pipe", 30% unlabeled, no "pump", "motor", or "gauge" | 58 s total | Not measured | Roihu L40 |
| 2026-11-07 | Viktor | 3D objects from masks (`app/extract/lift.py`) | 700 views, 30,521 masks | IoU above 0.3, at most 3 m | 441 objects, median size 0.67 m, seen in median 23 views. 306,360 splats tagged (26%). Labels weak: 251 "pipe", 0 "pump" | 15 s | Not measured | Roihu L40 node |
| 2026-11-07 | Viktor | Qwen3.5-4B labels on single-view crops | 60 crops from 20 views | Fixed label list, masked crop | 28 unknown. Finds real motors and tanks, but the "pump" labels I checked were wrong. Confidence is only ever 0 or 0.9 | 0.94 s per crop | 9.4 GB VRAM | Roihu L40 |
| 2026-11-07 | Viktor | Object label benchmark, 48 random objects, rough hand labels | `lift_v1` objects | Compared with SAM labels at 54% exact | Qwen3.5-4B: 1 view 52%, 3 views 62%, 5 views 65%. Qwen3.5-9B 3 views 54%, with 22 wrong claims vs 15. Equipment accuracy not checked | Full run about 6 min | | Roihu L40 |
| 2026-11-07 | Viktor | Labels against an AI visual review of the 210 largest objects (not human-verified) | `lift_v1` objects | SAM, Qwen3.5-4B with 5 views, graded rule | Named labels agreeing with the review: SAM 52%, Qwen 59%, graded 78% (94 of 210 named). Qwen said pump 17 times; only about 2 matched | | | Roihu L40 |
| 2026-11-07 | Viktor | Real routing on `Equipment Room.ply` (`app/nav/route.py`) | `lift_v1` objects | 5 cm cells, 0.6 m body, 52 movable footprints | Connected floor 6.9 to 7.4 m2 after leaving out movable objects and low clutter. To obj-0046: 3.2 m, stops 1.24 m away. 153 of 441 objects reachable within 1 m | Under 0.1 s per route | | ThinkPad |
| 2026-11-07 | Viktor | Own 3DGS (`app/scene/train_splat.py`) | COLMAP cameras, 1,179 frames | 30,000 steps, gsplat | 3,184,658 splats, 752 MB, held-out 26.41 dB on 187 frames | 25 min | 5.9 GB VRAM | Roihu L40 |
| 2026-11-07 | Viktor | COLMAP, 1,500 frames | `Industrial Boiler Room` video | OPENCV, sequential, loop detection | 1,496 frames in one model, 252,645 points, 1.06 px. Job crashed on exit, output complete | About 4.5 h | 8.6 GB RAM | Roihu, 32 CPUs |
| 2026-11-07 | Viktor | Labelling by matching image features, held out, against an AI review of 441 objects (not human-verified) | 362 named objects | 5-nearest neighbours | CLIP B/16 62%, L/14 63%, DINOv2 B 61%, L 57%, vs Qwen 54%, SAM 52%. Finds tanks and pipes; no feature set found valves, and at most 1 of 4 pumps | Minutes | | Roihu L40 |
| 2026-11-07 | Viktor | Object look: meshes vs fitted shapes | `lift_v1` objects | Depth-fused meshes on 10 objects, and cylinders and boxes on tanks, buckets, boxes, cabinets | Meshes are bumpy, thin parts break up, pumps look like rocks. Shapes look clean: 48 of 60 fit above score 0.5, 18 cylinders, 30 boxes. Some tanks score low | Seconds locally | | ThinkPad, Roihu CPU |
| 2026-11-06 | Viktor | Pi3X | 100 frames, 672x378 | Confidence above 0.5 | 1.73M points, layout looks fragmented | 15.6 s inference | 29.2 GB VRAM | Roihu L40 |
| 2026-11-06 | Viktor | COLMAP extract and match | 1,500 frames | OPENCV, sequential, loop detection | Mapping still running at last check | 60 s + 466 s | Not measured | Roihu, 32 CPUs |
| 2026-11-07 | Eduard | Floor map (`app/nav/grid.py`) | Cleaned `Equipment Room.ply` | 5 cm cells, body 0.15-1.9 m, opacity above 0.3, 3 hits | 33.8 m2 free. Connected: 11.0 m2 at 0.3 m wide, 7.6 at 0.6, 4.0 at 1.0, 0.4 at 1.5. Stricter noise settings reach 13.0 at 0.6. Not checked against the views | 3.6 s | Not measured | ThinkPad |
| 2026-11-07 | Viktor | Floor map with space carving (`app/nav/carve.py`) | Own splat, 689 rendered views, 1,496 camera positions | Rays must end in a spot at least 20% of the time, 0.3 m corridor along the camera path | Connected at 0.6 m wide: 0.2 to 6.6 m2, 28.2 m2 free, 190,844 floating splats removed. Blocked cells on the camera path fell from 35% (depth counts) to about 3% (carving without the corridor). Camera 1.28 to 1.40 m above floor, which supports metres but doesn't prove them | 32 s carving | Under 40 GB RAM, not measured | Roihu CPU |
| 2026-11-07 | Viktor | Routes to pump and motor candidates | Own splat, `lift_v2` | 0.6 m wide | All 30 reachable. Checked by eye: real pumps include `obj-0048` and its twin, and the red circulator `obj-0049`; many Qwen pump labels are wrong | Under 1 s per route | | Roihu CPU |
| 2026-11-07 | Eduard | A* speed (`app/nav/route.py`) | Floor map of `Equipment Room.ply`, longest test about 4.7 m | Robot, person, carrying | 18, 10, 5 ms per route, in pure Python | Under 20 ms | Not measured | ThinkPad |
| 2026-11-07 | Eduard | Robot and person routes (`app/nav/route.py`) | `splat_v2` grid, 574 objects, 19 movable footprints | Robot 0.3 m wide up to 0.6 m tall, person 0.6 m wide up to 1.9 m tall | Connected floor: robot 16.7 m2, person 6.2 m2. Within 1 m of an object: robot 458, person 402 of 555. To `obj-0048`: robot 6.66 m, person 6.83 m | 36 and 16 ms per route | Not measured | ThinkPad |
| 2026-11-07 | Eduard | Copilot through the API (`app/api/copilot_link.py`) | `splat_v2` objects, Excel pack | `POST /api/copilot/query` | `P-005` diagnosis, service history and route answered with citations. Only 1 of 574 objects has an Excel record | | | ThinkPad |
