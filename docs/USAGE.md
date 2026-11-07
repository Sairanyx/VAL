# Usage guide

How to run the demo, use the viewer, and fix what goes wrong.

## Set up
You need `gh auth login` once, plus two files from Viktor that aren't in git:
- `Equipment Room.ply`, in `data/scene/equipment_room/`
- The Excel pack, in `data/`, as any `.xlsx` file

```bash
git pull
make scene      # objects, floor map, and light scenes
make mapping    # links Excel records to objects, writes assets_mapped.json
make pieces     # cuts movable objects out of the scene
make highlights # exports cyan segmented surfaces for object selection
make db         # optional, needs Docker: keeps changes after a restart
make model      # optional, about 20 GB: the copilot's language model
```
Run these with internet. The demo itself needs none.

## Run it
**The short way:** `./start browser` on a laptop or PC, or `./start tablet` for the Lenovo. Each starts the
database, API, and viewer, and prints the address to open. Ctrl+C stops it. `make start-browser` and
`make start-tablet` do the same.

**Step by step:** Use two terminals. **Both must run, and both must use the same objects.**
```bash
make api
make web SCENE=data/scene/equipment_room/cut/base.ply ASSETS=data/scene/equipment_room/assets_mapped.json SHAPES=data/scene/equipment_room/shapes.json PIECES=data/scene/equipment_room/cut
```
Open http://localhost:8000. On a tablet on the same network, use `http://<this machine's IP>:8000`.

For a tablet or a laptop without a good GPU, cut a lighter scene first:
`make pieces PIECES_FROM=data/scene/equipment_room/light_full.ply`

## Highlight an object's surface
Run `make highlights`, then restart your viewer. Clicking an object tints its segmented
splats cyan and hides its selected box; selecting another object replaces the highlight.
The highlight follows dragging and undo and is independent of the **Boxes** toggle.

The three cut-out movable objects highlight their whole cut piece, the same splats that move when
dragged, so run `make pieces` before `make highlights`. Other objects show detected surfaces only:
missed parts remain missing. Operator-added objects have no segmentation yet; a message explains this.
**Objects** mode still shows fitted shapes instead of scanned surfaces.

Generate highlights from the original PLY, not `cut/base.ply` or a reduced scene: labels index the
original scene. Generated highlights are loaded automatically for scenes under `SCENE_DIR`.
For a different scene, pass its own `HIGHLIGHTS=path/to/highlights`, or disable loading with
`HIGHLIGHTS=`.

## Move an object
1. Tap the object. The smallest box under your finger is selected.
2. Press **Move on floor**. Only movable objects have this button.
3. Drag anywhere on the screen. The object follows your drag across the floor.
4. Release to save. If a route is showing, it plans again.
   - If the spot is taken, the object and whatever's in its way turn red, and the panel says why.
   - Releasing on a red spot puts it back at the last good spot. A wall or fixed equipment blocks it too.
5. **Undo changes** puts everything back.

**Try this first:** the roll cage `obj-0067`. Plan a route with **Go to P-005** from the middle of the room,
then drag the cage onto the route. The route bends around it. To drag from a better view without changing
the route, press **Walk** to switch to **Fly** first.

Every movable object moves as the real scan, including split and combined ones. `obj-0067`, `obj-0021`, and
`obj-0112` are cut in advance by `make pieces`, with the floor behind them patched, so they look cleanest.
Others are cut by their box when you press **Move on floor**, which takes a moment. Anything else in the box
moves too, and the floor they leave may look dark. If it can't be cut, the outline moves instead, and the
panel says so. This needs `Equipment Room.ply` in `data/scene/equipment_room/`.

### What happens when you move something
```text
Tap object            web/main.js: finds the box under your finger, opens the panel
Move on floor         web/objects.js: refuses anything that isn't movable
Drag                  web/objects.js: moves the box, shape, and scan piece. Only on this screen so far
                      POST /api/objects/ID/check-move: app/api/collisions.py says if it fits, for the red warning
Release               web/objects.js: records the move
                      web/route.js: POST /api/changes, through web/serve.py to the backend
Backend               app/api/main.py: refuses a bad spot, even if the viewer's check was skipped
                      app/api/store.py: refuses unless movable, moves the box, logs the change
                      app/api/db.py: saves it, if the database is running
Route showing?        web/route.js: POST /api/route. While dragging it previews the route with the object there.
                      A refused drop plans again, so the route never bends around a spot it didn't reach
                      app/nav/route.py: the moved box now blocks the map, so it plans around it
Reload the page       web/main.js: GET /api/assets, and restores saved moves on screen
Undo changes          web/route.js: POST /api/changes/reset
```
The floor map never changes. Movable objects aren't in it: they're added on top for each route. Other open
screens only pick up changes when reloaded.

## Add a missed object
1. Press **Add object**, then drag a box around it or tap it.
2. Check the orange box. Use **Bigger** or **Smaller** if it's off.
3. Check the type and whether it can move. A model suggests these if `make model` has run.
4. Press **Save**. It blocks routes straight away and is marked "new, unconfirmed".

## Split an object that's really two things
1. Tap the object, and press **Split into two**. Objects linked to a record can't be split.
2. Drag a box around one part. Orange is what you selected, and blue is the rest.
3. Check the type and whether each can move, then press **Save**. Both are marked "new, unconfirmed".

Split or combine before moving: a moved object has to be put back first, with **Undo changes**.

Set a part to movable to move it, and its real splats go with it. **Undo changes** brings the original back.

## Combine objects that are really one thing
1. Tap the first object, and press **Combine with...**. Objects linked to a record can't be combined.
2. Tap the second object. An orange box appears around both.
3. Check the type and whether it can move, then press **Save**. **Undo changes** brings the originals back.

## Ask the copilot
Select an object and press **Ask copilot**, or press **Copilot**. The note under each answer says whether the
model worded it or it's a fixed template. Unsafe requests are refused.

## Other controls
| Control | What it does |
|---|---|
| **Go to P-005** | Plans a route to the faulty device from where you stand. Arrows show the way |
| **Walk / Fly** | In **Walk** the route starts from wherever you move to. In **Fly** you can look around from anywhere, and the route keeps its start |
| **Walk route** | Walks the route, and stops looking at the device |
| **Person / Robot** | Changes the body size and height for routes |
| **Range** | How far away frames and labels show |
| **Boxes on** | Shows or hides frames |
| **Scan / Both / Objects** | The real scan, fitted shapes over it, or shapes only |
| **Apart** | Pulls objects apart to show them separately |
| **Phone** | Turn the device to look, and walk to move. Needs `make web HTTPS=1` |

Add these to the URL: `?lod=0&res=2` for the sharpest image, or `?res=0.5` if it's slow.

## If something's wrong
| What you see | Why | Fix |
|---|---|---|
| "Backend not connected" | `make api` isn't running | Start it. Check http://localhost:8001/docs |
| "Backend has different objects" | `make web` and `make api` use different files | Pass `ASSETS=data/scene/equipment_room/assets_mapped.json` to `make web` |
| `make api` fails on a missing file | `make mapping` hasn't run | Run `make scene mapping` |
| No **Move on floor** button | The object is fixed or unsure | The panel says which. Try `obj-0067` |
| Box goes red and panel says "Can't place it here" | That spot is taken | Drop it somewhere else. Tiny overlaps are allowed, because boxes are loose |
| Route jumps or disappears as you look around | You're in Walk mode, so it starts from where you are | Press **Walk** to switch to **Fly**, then **Go to P-005** again |
| Only an outline moves | The backend couldn't cut it | Check `make api` is running and `Equipment Room.ply` is in place |
| Object moves, but no route change | No route showing, or it isn't in the way | **Go to P-005** first, then drag onto the line |
| "Couldn't save the move" | The backend refused it or is down | The message says why. Restart `make api` if needed |
| "Couldn't add an object: Selecting needs the scene" | `Equipment Room.ply` is missing | Put it in `data/scene/equipment_room/` |
| "No route to..." | Something blocks the way | That can be correct. **Undo changes** if you caused it |
| Everything is back after reloading the backend | No database | Run `make db` before `make api` |
| Blurry or slow | Heavy scene on a weak GPU | Try a lighter scene, or `?res=0.5` |
| Viewer shows a small test scene | `make web` had no `SCENE=` | Use the full line above |
| Old object IDs, such as `obj-0046` for P-005 | Old data | Run `make scene mapping pieces highlights` again |
| `obj-0008`'s seat has no star base | An old `cut` folder from before it left the moving list | Run `make pieces highlights` again |

Open the browser's developer console (F12) for more detail, and include any red errors when asking for help.

## Tablet mode
Touch screens get it automatically. `?tablet=1` or `?tablet=0` in the address forces it. Windows have no
close button: tap a window anywhere except its controls to close it. It also draws at 0.75 resolution,
aims for 500,000 splats, and loads `light_full.ply` when `make web` finds one (`?scene=full` overrides). Change these with `?res=` and `?splats=`. For a tablet, also cut a lighter scene:
`make pieces PIECES_FROM=data/scene/equipment_room/light_full.ply`.

## Control the viewer with commands
Every button has a command, so a voice copilot can do the same things. `GET /api/viewer/actions` lists them.
```bash
curl -X POST localhost:8001/api/viewer/commands -H 'Content-Type: application/json' \
  -d '{"action": "route_to", "args": {"object_id": "obj-0049"}}'
```
The open viewer runs it within about half a second. `GET /api/viewer/commands/ID` shows the result. Adding,
splitting, and combining only start from a command, because a person draws or taps the rest.

