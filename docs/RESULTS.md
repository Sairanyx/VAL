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
| 2026-11-06 | Viktor | Pi3X | 100 frames, 672x378 | Confidence above 0.5 | 1.73M points, layout looks fragmented | 15.6 s inference | 29.2 GB VRAM | Roihu L40 |
| 2026-11-06 | Viktor | COLMAP extract and match | 1,500 frames | OPENCV, sequential, loop detection | Mapping still running at last check | 60 s + 466 s | Not measured | Roihu, 32 CPUs |
