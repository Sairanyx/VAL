# Plan

We're building a tablet-friendly web demo of a navigable digital twin of a plant room, running entirely
on site. Everyone can start now against `fixtures/sample_assets.json`, then swap in real data.

Requirements and scoring are in `docs/CHALLENGE.md`. Sections marked "future" are for the pitch and
aren't built this weekend.

## The demo
1. **Open the room:** the 3D scene shows a frame around every detected object.
2. **Tap an object:** see its type, status, telemetry, alarms, and documents.
3. **Ask or tap "Navigate":** a collision-free route appears, and an avatar walks it.
4. **Walk the route:** nearby objects highlight and show their status.
5. **Reach the fault (`P-005`):** the copilot explains it, cites evidence, and suggests safe checks.
6. **Separate the scene:** objects turn into colored assets and pull apart. Select, drag, or remove one,
   or add an obstacle, and the route updates.

Step 6 follows Valmet's "Every object, its own asset" video (`semantic extraction demo 1`). Their
engineer said it would earn extra credit, though it isn't in the written scoring. Steps 1-5 come first.

## Who does what
Swap freely if someone's skills fit another area better. Update this table and `AGENTS.md` if you do.

| Person | Area | Folder | Score |
|---|---|---|---|
| **Viktor** | Scene loading, cleaning, rendering, own splat | `app/scene/` | Enables all |
| **Sasha** | Asset extraction, 3D boxes, splat tags | `app/extract/` | 30% |
| **Eduard** | Floor, routing, nearby search, backend API | `app/nav/`, `app/api/` | 25% + 15% |
| **Hannu** | Excel data, asset mapping, AI copilot | `app/copilot/` | 20% + part of 30% |
| **Benjamin** | Web viewer, tablet, demo video, slides | `web/`, `docs/` | 10% + 25% display |

## First tasks
**Viktor**
1. Write `app/scene/load.py`: read a splat PLY and filter it by opacity and size.
2. Render color and depth views with known cameras, for Sasha to use.
3. Check the COLMAP result, train 3DGS if it's clean, and compare it with `Equipment Room.ply`.
4. Split the scene using `splat_labels.npy`: one PLY per object plus a background, each with a tint.

**Sasha**
1. Run SAM and CLIP on sample video frames to find which settings detect the most useful objects.
2. Project masks into 3D using Viktor's views, and merge them across views.
3. Write real `assets.json` and `splat_labels.npy`, and count how many objects it finds.
4. Once boxes work, try VLM labels and junk filtering. Keep them only if they beat CLIP on 20-30
   hand-labelled objects.

**Eduard**
1. Build the API from the fixture, with the routes below, so Benjamin can connect straight away.
2. Write `app/nav/`: find the floor in `Equipment Room.ply` and build an occupancy grid.
3. Add A* routing with a body-width margin, then nearby search. Expose both as copilot tools.
4. Keep the permanent floor map separate from object footprints, and combine them when routing, so
   moving or removing an object updates routes without rebuilding the map.
5. Rehearse the full demo with the internet disconnected.

**Hannu**
1. Load the Excel workbook into a simple local store, and read its `DOC-RAG-GUIDE` rules.
2. Write `mapping.json`: match objects to records by class, with `P-005` as the faulty target.
3. Pick a local LLM such as Qwen. Build the copilot tools and the `P-005` diagnosis with checked
   citations, then status along the route, then the conversation flow below.
4. Write 10-15 test questions with expected answers, including ones it should refuse.

**Benjamin**
1. Test whether a real tablet can show the splat in Viser. Try a reduced scene if it struggles. Also
   test whether it can draw many separate splat objects and move them. This decides the viewer.
2. Choose Viser or a small three.js page, with all assets served locally. Show the fixture's boxes.
3. Add the route, walking avatar, nearby highlights, and chat with citations. Then own the video and
   5-8 slides.
4. Add the separated view: colored objects with labels, pull-apart, select, and drag.

## Pipeline
```text
OFFLINE, once per scan
Scene (.ply) → clean → render views → SAM → CLIP/VLM → 3D boxes ─→ assets.json
                 │                              └─ tag each splat ─→ splat_labels.npy
                 │                                                       │
                 │                               split scene ─→ objects/*.ply + background.ply
                 │                                    Excel pack ─→ mapping.json
                 └─ floor + obstacles ─→ permanent floor map + object footprints

LIVE, in use
Tablet viewer ⇄ Backend API ⇄ routing, device data, change log, local AI copilot
```

**Choose the scene (Viktor):** `Equipment Room.ply` is the default. Our own splat (video, sharp frames,
COLMAP, 3DGS) is confirmed as allowed. Run the pipeline on both, and keep the one with better boxes and
routes. Pipeline code must work with either.

**Offline**
1. **Clean (Viktor):** remove nearly transparent and oversized splats. Keep the original coordinates.
2. **Render (Viktor):** place cameras through the room and render color and depth. With our own splat,
   real video frames and COLMAP cameras may give better masks.
3. **Find objects (Sasha):** SAM outlines as much as it can, since asset count drives the top score.
4. **Name objects (Sasha):** CLIP gives a fast label. A VLM can improve the merged objects.
5. **Build boxes (Sasha):** project masks into 3D with depth, merge across views, and fit boxes.
6. **Tag splats (Sasha):** each splat votes across the views that see it. With no clear winner, it's
   background. Test this early, because it decides how clean moved objects look.
7. **Split (Viktor):** write one PLY per object and a background, with a tint for the separated view.
8. **Map data (Hannu):** attach Excel records by class. Objects with no record stay plain detected
   objects.
9. **Floor map (Eduard):** fit the floor, block anything at body height, widen obstacles by a body-width
   margin, and keep the connected floor. Permanent obstacles and object footprints stay in separate
   layers.

**Live**
1. **Open (Benjamin):** load the scene, reduced if the tablet needs it, plus `GET /api/assets`.
2. **Details:** `GET /api/assets/{object_id}` joins the mapping, telemetry, alarms, and documents.
3. **Route:** `POST /api/route` runs A* to free floor beside the object.
4. **Nearby:** `GET /api/nearby` drives highlights as the avatar moves.
5. **Ask:** `POST /api/copilot/query` answers with tools, citations, and app actions.
6. **Change:** `POST /api/changes` logs an add, move, or remove and updates footprints. The base scan is
   never overwritten, so everything can be reset.

## Copilot
The LLM explains facts and doesn't produce them. It asks tools for facts, and code checks its answer:

```text
Question → LLM picks tools → code returns facts with IDs → LLM answers → code checks citations → tablet
```

### Example conversation
> **Operator:** Where's pump P-005?
> **Copilot:** It's in this room. *(It highlights in 3D, with a Navigate button.)*
>
> **Operator:** What's wrong with it?
> **Copilot:** Attention required, health 44, fouling. Observations and hypothesis are shown separately,
> with evidence IDs and a confidence.
>
> **Operator:** When was it last serviced?
> **Copilot:** Date and result, citing the work order.
>
> **Operator:** What should I check?
> **Copilot:** Steps, citing the document, and a reminder to follow site procedures.
>
> **Operator:** Take me there.
> *(The route appears and the avatar walks.)*

### Tools
| Question | Tool | Source |
|---|---|---|
| Where is it, or what matches? | `find_assets`, `plan_route` | `assets.json`, `mapping.json`, floor map |
| What's wrong? | `get_status`, `get_telemetry`, `get_events` | `Current_State`, telemetry, alarms |
| Last service? | `get_maintenance` | `Maintenance_History` |
| Seen this before? | `search_cases` | `Historical_Service_Cases` |
| What should I check? | `search_docs` | `Knowledge_Docs`, any manuals |
| What's near me? | `get_nearby` | `assets.json`, current position |

### What the operator gets
| Task | Priority |
|---|---|
| Fault diagnosis on arrival | Must have |
| Status along the route (the brief scores this) | Must have |
| Why this device comes first: criticality, condition, uncertainty | High |
| Natural search, such as "show degraded pumps" | High, and a strong demo moment |
| Follow-up questions from maintenance history | High |
| Work-order draft for a person to approve | Medium |
| Handover summary | Nice to have |

### How it should behave
- **Current machine:** the app remembers the machine in focus, so "it" works. Tapping an object sets it.
- **Matching machines:** code matches tags and types, so "P-005" and "pump 5" reach the same record. If
  there are several matches, it asks. It never guesses.
- **App actions:** answers can return `highlight`, `show_route`, or `open_document`, linking chat to 3D.
- **Logs and manuals:** filter logs by asset ID with normal queries. Search manuals by section with local
  embeddings and keywords, and keep the document and section for citations.
- **Missing evidence:** it says it couldn't find that, and doesn't fill the gap from general knowledge.

### Rules enforced in code
- **Citations:** reject or retry any answer citing an ID that no tool returned.
- **Numbers:** code calculates trends, thresholds, and routes. The LLM only describes them.
- **Confidence:** comes from model confidence, the `Data_Quality` sheet, and mapping confidence.
- **Observation and hypothesis:** separate fields, so the UI can show them differently.
- **Safety:** recommends checks and escalation only. It can't control equipment (`DOC-FIELD-SAFETY`).
- **Mapping:** show when a record was attached procedurally (`DOC-3D-MAPPING`).

### Keeping it reliable
- **Route commentary:** pre-generate it or use templates, so the walk never waits for the model.
- **Main diagnosis:** keep a saved `P-005` answer in case the model fails during the pitch. Say so if used.

### Data limits
The pack has 8 short guidance documents and service data, not full manuals. Its 38 RAG files and full
telemetry CSV weren't supplied, so ask Valmet. Public manuals are fine if labelled as such.

## Where VLMs fit
These run offline, and their results are saved, so the demo doesn't need the VLM loaded. A single
Qwen-VL model might also serve as the copilot's LLM. Hannu tests this.

| Task | How |
|---|---|
| Better labels | Choose a type from a set list, or "unknown" |
| Filter junk | Ask whether a box is one real object |
| Descriptions | A short description, for objects with no Excel record |
| Visible text | Read text like "Grundfos" exactly as written. Add local OCR if the VLM misreads it |
| Mapping suggestions | Propose matches for an engineer to confirm (future) |

Use CLIP across all masks, and send only merged objects to the VLM. A VLM can invent answers, so keep a
confidence and never treat text it read as proof of an Excel identity. Small text needs sharp real
frames, as splat renders will probably blur it.

## Movable objects
The scan is a fixed background, with objects in an editable layer and a log of changes on top.

| Change | Scene | Floor map | Data |
|---|---|---|---|
| Something appears | Add a simple box | Block its footprint | New object, marked unconfirmed |
| Something leaves | Hide its splats | Clear its footprint | Mark as removed, keep history |
| Something moves | Move its splats | Clear the old spot, block the new one | Same identity, new position |

**Known problems:** removed objects leave holes the scan never saw, splats at object edges may be
mixed up, and moved objects keep their old lighting. Pick the cleanest objects for the demo, and only
make the clear ones movable. If the viewer can't handle moving splats, use point clouds for moved objects.

**Detecting changes:**
1. **Manually on the tablet:** "Add obstacle" or "Removed". This is what we demo.
2. **Short clip (future):** film the area, locate the frames in the scene, compare against a render of
   the old scene, and have an engineer confirm. Only that area updates.
3. **Fixed cameras or a patrol robot (future):** the same comparison, run regularly.

## Runs entirely on site
Plant data never leaves the site, which is a key selling point. The brief doesn't score privacy
directly, so pitch it as innovation and real-world fit.

- **Nothing external at runtime:** no cloud APIs, hosted models, CDN scripts, or web fonts.
- **Copilot:** use a local LLM and local embeddings, sharing the 5090's memory with everything else.
- **Tablet connection:** bring our own router, and don't rely on venue Wi-Fi.
- **Roihu:** for experiments only. The final pipeline must also run on the 5090.

### Compute estimates
Replace these with measured numbers in `docs/RESULTS.md`.

| Stage | Hardware | Time | Memory |
|---|---|---|---|
| Offline on a provided splat | 5090 | 1-2.5 hours, or 30-60 minutes without a VLM | Up to 20 GB VRAM per step |
| Building our own splat | CPU and 5090 | 1.5-3 hours more | About 8 GB RAM measured for COLMAP so far, up to 16 GB VRAM for 3DGS |
| Live demo | 5090 | Continuous | 10-25 GB of 32 GB VRAM |

### Deployment at a plant (future)
**Suggested spec:** one 24-32 GB GPU, at least 16 CPU cores, 64 GB RAM, about 100 GB of disk per site,
local Wi-Fi, and recent tablets.

| Stage | What happens | Who |
|---|---|---|
| 1. Install | Set up the server with models preloaded, on a private network | Integrator or plant IT |
| 2. Scan | Walk the area with a phone or scanner, and upload to the server | Technician |
| 3. Process | Frames, cameras, splat, objects, floor map, and a quality report | Automatic |
| 4. Review | Fix labels, confirm equipment links, test routes | Maintenance engineer |
| 5. Publish | Make the checked version live, keeping the old one for rollback | Maintenance engineer |
| 6. Use | Alarm opens on a tablet, follow the route, ask the copilot, draft a work order | Technician |
| 7. Update | Small changes in the app or by clip. Full rescan only when a lot has changed | Technician or engineer |

**After a rescan,** match new boxes to old ones by position and type. Same place and type keeps its
confirmed identity. Moved, new, or missing objects go to the engineer.

**What the demo simplifies:**
| Area | Demo | Real deployment |
|---|---|---|
| Device data | Synthetic Excel pack | Read-only link to OPC UA, MQTT, or the maintenance system |
| Object identity | Rule-based mapping | Confirmed by engineers, with QR or NFC tags where needed |
| Technician position | Simulated from a chosen start | QR checkpoints or AR tracking |
| Network and access | Our own router | Plant IT's isolated network, with sign-in |
| Work orders | Draft at most | Connected to the maintenance system, with human approval |

Linking objects to real equipment is the hardest part of a rollout. Say so in the pitch.

## Shared data
Generated files go in `data/scene/<scene_id>/`, which isn't in git. All coordinates use the original
scene's axes, so +y points down in `Equipment Room.ply`. Each file has one owner.

| File | Owner | Contents |
|---|---|---|
| `assets.json` | Sasha | Objects with label, confidence, center, and box. See the fixture |
| `splat_labels.npy` | Sasha | One integer per splat: its object's index in `assets`, or -1 for background |
| `objects/*.ply`, `background.ply` | Viktor | The scene, split by object |
| `mapping.json` | Hannu | `object_id` to `asset_id`, `tag`, `method`, and `confidence` |
| `nav_grid.npz` | Eduard | Permanent occupancy grid, origin, cell size, and floor height |

Objects with no Excel record keep `mapping: null` and show as detected objects. Never invent an ID.

## API
Eduard owns this, and it extends the Excel pack's `API_Contract` sheet. Agree changes with Benjamin.

| Route | Returns |
|---|---|
| `GET /api/assets` | All objects with boxes, mapping, and status |
| `GET /api/assets/{object_id}` | One object with telemetry, events, and documents |
| `GET /api/nearby?x=&y=&z=&radius=` | Objects near a point |
| `POST /api/route` with `start` and `object_id` | `path` (list of points) and `length` |
| `POST /api/copilot/query` with `question` and optional `object_id` | `answer`, `observations`, `hypotheses`, `citations`, `confidence`, and `actions` |
| `POST /api/changes` with `op`, `object_id`, and `position` | Logs an add, move, or remove. Later routes use it |

## Milestones
Check the submission deadline with the organizers, then adjust these.

| When | Goal |
|---|---|
| **Tonight** | Fixture works end to end: viewer, API, a fake route, and a stub copilot answer |
| **Saturday midday** | Real scene, real boxes, and a real route in the viewer |
| **Saturday evening** | Full demo on real data, then the separated view. Choose the scene. Stop adding features |
| **Sunday morning** | Fix bugs, rehearse offline, record a backup video, finish slides and technical note |

## Tracking results
No MLflow: we mostly run pretrained models a few times. Each run saves `runs/<name>/summary.json`, and
runs worth keeping get a line in `docs/RESULTS.md`. Everyone adds their own.

## Side challenges
Optional, and only after the main demo works. Ask the MLH coach whether we can enter alongside Valmet.
- **Entire:** a good fit for our workflow. Everyone runs `make entire` once. See `docs/ENTIRE.md`.
- **Tiger Data:** possible for telemetry if self-hosted TimescaleDB qualifies. Hannu decides later.
- **Skip the rest:** the cloud options break the on-site rule, and Solana doesn't fit this project.

## Getting started
- **Scene and data:** get `Equipment Room.ply` and the Valmet folder from Viktor, not from git.
- **Check your copy:** the SHA-256 of `Equipment Room.ply` starts `83d8c7d99316c08c`.
- **GPU:** the 5090 is shared, so agree who's using it. Roihu needs `project_2020113` membership, so ask
  Viktor. Most ThinkPads can only handle coding and the viewer.
- **Git access:** the repo is private. Use SSH (`git remote set-url origin git@github.com:Sairanyx/Newbies.git`)
  or log in with `gh auth login`.
- **Merging:** merge small changes often, and tell the team when a shared file's format changes.
