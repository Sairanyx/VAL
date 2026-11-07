# Challenge: Industrial Metaverse (Valmet)

Summary of the official brief, which is the docx in `Valmet_SinceAI2026 _1_/` (not in git).
Questions go to the Since AI Discord challenge channel. Event: 6-8 Nov 2026, Turku.

**Guiding question:** how might we extract maximum semantic asset information and walkable paths
from the scene, so a simulated avatar or robot can navigate to a faulty device, show nearby framed
assets with their data, and deliver AI service guidance?

**Valmet's wider vision:** their representative described a person using this on a tablet to see
segmented objects with details and navigate to one. The written brief says not to spend time on a
mobile or Android frontend. So we build a browser app that works on a tablet, not a native app.

**Extra credit (verbal, from their engineer):** turn the scene into separate objects that can be
moved, like `semantic extraction demo 1` ("Every object, its own asset": select, move, simulate).

## What to build
Focus on backend and spatial processing, and keep the UI lightweight.

1. **Extract assets:** detect and put 3D boxes around as many objects as possible in
   `Industrial Boiler Room.ply`.
2. **Map metadata:** link extracted assets to the Excel pack. Random or procedural mapping is
   allowed, with a pre-determined faulty target device.
3. **Navigate:** a worker or robot follows an automatic, collision-free route on the floor to the
   faulty device.
4. **Show nearby assets:** highlight 3D boxes and metadata for assets near the avatar as it moves.
5. **Diagnose:** on arrival, an AI assistant explains the fault and recommends next steps, grounded
   in the Excel pack.

## Scoring
| Weight | Criterion |
|---|---|
| 30% | Number and quality of extracted, 3D-framed assets mapped to metadata |
| 25% | Realistic obstacle-free navigation and proximity display |
| 20% | AI diagnostics, grounding and explainability |
| 15% | Backend architecture: structured, automated, modular |
| 10% | Demo clarity and innovation |

## Submission
- Working demo, runnable locally or clearly recorded
- Repo with a concise README and setup instructions
- 5-8 slides: extraction pipeline, pathfinding, metadata mapping, AI approach
- Demo video, 5 minutes maximum
- Brief technical note on models, libraries, and software

## Data
| File | Contents |
|---|---|
| `Equipment Room.ply` | Restored Gaussian splat, spherical harmonics degree 3 (45 `f_rest`). Use this one |
| `Industrial Boiler Room (1).ply` | Damaged original. Don't use it |
| `Industrial Boiler Room (1).mp4` | 1080p walkthrough, 3,352 frames, 112 s, no camera poses supplied |
| `semantic extraction demo 1/2` | Reference videos of the desired output (different sites) |
| `Valmet_..._Builder_Pack (1)...xlsx` | 30 assets, states, alarms, work orders, service cases, docs |

Asset classes: 12 control valves, 6 pumps, 6 motors, 3 pressure transmitters, 3 vibration sensors.
The pack is synthetic. Its `Scene_Anchors` coordinates are placeholders, not real scene positions.

AI answers must follow the pack's rules: `DOC-RAG-GUIDE` (name the asset, cite evidence IDs, give
confidence, separate observation from hypothesis), `DOC-FIELD-SAFETY` (recommend verification, not
autonomous action), and `DOC-3D-MAPPING` (never silently guess identity, so store how each asset
was mapped and with what confidence).

## Scene input rule
The brief names Valmet's PLY as the input, but we have confirmation (reported by Viktor, 2026-11-06)
that we may use our own splat. We compared them and the demo uses the uncleaned `Equipment Room.ply`,
so say that in the technical note.

## Known data problems (as of 2026-11-06)
- **`Industrial Boiler Room (1).ply` is damaged.** 67% of its records look like random bytes.
  SHA-256 starts `117195366421b07a`. It's replaced by `Equipment Room.ply`.
- **`Equipment Room.ply` is valid:** all 1,676,481 records, SHA-256 starts `83d8c7d99316c08c`. With
  opacity above 0.1 it spans about 9.1 x 2.55 x 7.3 scene units. +y points down (the floor is at
  y of about 1.25). Units look close to metres, but that's unconfirmed.
- **The brief still names the old file.** Confirm the new name is acceptable when submitting.
- **Files the pack mentions are missing:** `telemetry_full_14d_30min.csv` (the workbook has a 3-day
  sample) and the 38 RAG markdown files (the workbook has 8 core docs).

## How we cover the brief
Checked against the docx, 2026-11-07.

| Required | State | Where |
|---|---|---|
| Extract and 3D-frame as many assets as possible | Done: 440 objects. Precision sample still to score | `app/extract`, frames in the viewer |
| Map statuses, telemetry and metadata, with a faulty target | Done: all 30 records, procedural and marked, `P-005` as the fault. The other 410 objects have no record, as the pack only holds 30 | `app/copilot/mapping.py` |
| A worker or robot walks an automatic, collision-free route | Done, from the operator's own view: the camera is the worker, and the minimap shows where they are. A* on the floor map, for a person or a robot, re-planned when things move. No figure is drawn, by choice: say so in the video | `app/nav`, `web/route.js` |
| Highlight frames and Excel metadata nearby, along the way | Done: frames within range, and labels with status and health from the record. Attention-level devices are announced as you near them. The full record is a tap away | `web/main.js` |
| AI diagnosis triggered on reaching the device | Done: starts by itself, cites evidence IDs, gives confidence, safe checks only | `app/copilot` |
| Grounded in the Excel pack, per its RAG, safety and mapping rules | Done. 60-question test recorded, hand scoring still open | `docs/RESULTS.md` |
| Status along the path, from the AI (scoring criterion 3) | Partly: the status shows on labels and the Nearby line, but Val doesn't speak on the way | |
| Lightweight display | Done: a web viewer | `web/` |
| Modular, automated backend | Done: `make pipeline` from one config, but only dry-run from start to end | `scripts/pipeline.py` |
| Runnable locally or clearly recorded | Runs from a zip on Linux. Windows and Mac untested. Video not recorded yet | `make bundle` |
| Repo with a concise README and setup | Done. The team name is still a placeholder | `README.md` |
| 5-8 slides | Not done (Benjamin, with Sasha, Eduard, Hannu) | `docs/PITCH.md` |
| Video, 5 minutes at most | Not done (Benjamin). The form wants it ideally under 2 minutes, working in the first 20 seconds | |
| Technical note on models, libraries and software | Not done (Sasha) | |
| Extra credit: objects you can move | Done, by cutting each object's own splats. Only some cuts are clean | `app/scene` |

The brief names `Industrial Boiler Room.ply`: say in the technical note that we used its replacement,
`Equipment Room.ply`, from Valmet.
