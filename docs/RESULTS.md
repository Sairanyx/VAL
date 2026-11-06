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
| 2026-11-06 | Viktor | Pi3X | 100 frames, 672x378 | Confidence above 0.5 | 1.73M points, layout looks fragmented | 15.6 s inference | 29.2 GB VRAM | Roihu L40 |
| 2026-11-06 | Viktor | COLMAP extract and match | 1,500 frames | OPENCV, sequential, loop detection | Mapping still running at last check | 60 s + 466 s | Not measured | Roihu, 32 CPUs |
