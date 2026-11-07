# Results

One line for each run worth keeping. Raw outputs stay in `runs/` or on Roihu, not in git. These
numbers feed the scene comparison, slides, and technical note, so only record what was measured.

## Scenes
| Check | `Equipment Room.ply` | Own splat |
|---|---|---|
| Assets framed | Not run | Not built |
| Junk boxes, out of 30 sampled | Not run | Not built |
| Route reaches `P-005` without clipping | Not run | Not built |
| Floor area connected | Not run | Not built |

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
| 2026-11-06 | Viktor | Pi3X | 100 frames, 672x378 | Confidence above 0.5 | 1.73M points, layout looks fragmented | 15.6 s inference | 29.2 GB VRAM | Roihu L40 |
| 2026-11-06 | Viktor | COLMAP extract and match | 1,500 frames | OPENCV, sequential, loop detection | Mapping still running at last check | 60 s + 466 s | Not measured | Roihu, 32 CPUs |
| 2026-11-07 | Eduard | Floor map (`app/nav/grid.py`) | Cleaned `Equipment Room.ply` | 5 cm cells, body 0.15-1.9 m, opacity above 0.3, 3 hits | 33.8 m2 free. Connected: 11.0 m2 at 0.3 m wide, 7.6 at 0.6, 4.0 at 1.0, 0.4 at 1.5. Stricter noise settings reach 13.0 at 0.6. Not checked against the views | 3.6 s | Not measured | ThinkPad |
