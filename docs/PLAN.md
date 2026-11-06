# Plan

We're building a tablet-friendly web demo of a digital twin of the room. Each person can start now
against `fixtures/sample_assets.json`, then swap in real data as it's ready.

## The demo
1. Open the room: the 3D scene shows a frame around every detected object.
2. Tap an object: see its type, status, telemetry, alarms, and documents.
3. Tap "Navigate": a collision-free route appears and an avatar walks it.
4. Along the way, nearby objects highlight and show their details.
5. At the faulty device (`P-005`), the AI explains the fault, cites evidence, and suggests safe checks.

Requirements and scoring are in `docs/CHALLENGE.md`.

## Runs entirely on site
Plant data never leaves the site, which is a key selling point. One RTX 5090 server does the offline
processing and serves the app, and the tablet connects to it over the local network.

- **Nothing external at runtime:** no cloud APIs, hosted models, CDN scripts, or web fonts.
- **Copilot:** use a local LLM and local embeddings, sharing the 5090's memory with everything else.
- **Prove it:** rehearse the full demo with the internet disconnected. Eduard owns this check.
- **Roihu:** for experiments only. The final pipeline must also run on the 5090.

## Who does what
Swap freely if someone's skills fit another area better. Update this table and `AGENTS.md` if you do.

| Person | Area | Folder | Score |
|---|---|---|---|
| **Viktor** | Scene loading, cleaning, rendering, own splat | `app/scene/` | Enables all |
| **Sasha** | Asset extraction and 3D boxes | `app/extract/` | 30% |
| **Eduard** | Floor, routing, nearby search, backend API | `app/nav/`, `app/api/` | 25% + 15% |
| **Hannu** | Excel data, asset mapping, AI copilot | `app/copilot/` | 20% + part of 30% |
| **Benjamin** | Web viewer, tablet, demo video, slides | `web/`, `docs/` | 10% + 25% display |

## First tasks
**Viktor**
1. Write `app/scene/load.py`: read a splat PLY and filter it by opacity and size.
2. Render color and depth views with known cameras, for Sasha to use.
3. Check the COLMAP result, train 3DGS if it's clean, and compare it with `Equipment Room.ply`.

**Sasha**
1. Run SAM and CLIP on sample video frames to find which settings detect the most useful objects.
2. Project masks into 3D using Viktor's views, and merge them across views.
3. Write real `assets.json`, and count how many objects it finds.

**Eduard**
1. Build the API from the fixture, with the routes below, so Benjamin can connect straight away.
2. Write `app/nav/`: find the floor in `Equipment Room.ply` and build an occupancy grid.
3. Add A* routing with a body-width margin, then nearby search.

**Hannu**
1. Load the Excel workbook into a simple local store, and read its `DOC-RAG-GUIDE` rules.
2. Write `mapping.json`: match objects to records by class, with `P-005` as the faulty target.
3. Build the copilot on a local LLM: answers must cite event and document IDs, and give a confidence.

**Benjamin**
1. Test whether a real tablet can show the splat in Viser. Try a reduced scene if it struggles.
2. Choose Viser or a small three.js page, with all assets served locally. Show the fixture's boxes.
3. Add the route, walking avatar, and nearby highlights. Then own the video and 5-8 slides.

## Shared data
Generated files go in `data/scene/<scene_id>/`, which isn't in git. All coordinates use the original
scene's axes, so +y points down in `Equipment Room.ply`. Each file has one owner.

| File | Owner | Contents |
|---|---|---|
| `assets.json` | Sasha | Objects with label, confidence, center, and box. See the fixture |
| `mapping.json` | Hannu | `object_id` to `asset_id`, `tag`, `method`, and `confidence` |
| `nav_grid.npz` | Eduard | Occupancy grid, origin, cell size, and floor height |

Objects with no Excel record keep `mapping: null` and show as detected objects. Never invent an ID.

## API
Eduard owns this, and it extends the Excel pack's `API_Contract` sheet. Agree changes with Benjamin.

| Route | Returns |
|---|---|
| `GET /api/assets` | All objects with boxes, mapping, and status |
| `GET /api/assets/{object_id}` | One object with telemetry, events, and documents |
| `GET /api/nearby?x=&y=&z=&radius=` | Objects near a point |
| `POST /api/route` with `start` and `object_id` | `path` (list of points) and `length` |
| `POST /api/copilot/query` with `object_id` and `question` | `answer`, `citations`, and `confidence` |

## Milestones
Check the submission deadline with the organizers, then adjust these.

| When | Goal |
|---|---|
| **Tonight** | Fixture works end to end: viewer, API, a fake route, and a stub copilot answer |
| **Saturday midday** | Real scene, real boxes, and a real route in the viewer |
| **Saturday evening** | Full demo on real data. Choose the scene. Stop adding features |
| **Sunday morning** | Fix bugs, record the video as a backup, finish slides and technical note |

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
- **GPU:** the 5090 is shared. Roihu needs membership of `project_2020113`, so ask Viktor.
- **Merging:** merge small changes often, and tell the team when a shared file's format changes.
- **Tablet limit:** the app can't track a real person's position, so navigation is simulated.
