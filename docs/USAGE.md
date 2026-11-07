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
make bim        # simulated BIM model for BIM mode, plus model.ifc
make db         # optional, needs Docker: keeps changes after a restart
make laptop-model # optional, needs Ollama: Val's small model for a laptop with no GPU
make model      # optional, about 20 GB, for a GPU: Val's larger model
```
Run these with internet. The demo itself needs none.

## Run it
**The short way:** `./start laptop` on a ThinkPad or anything else with no graphics card, `./start browser` on a
PC with one, or `./start tablet` for the Lenovo. Each starts the
database, API, and viewer, and prints the address to open. Ctrl+C stops it. `make start-laptop`,
`make start-browser` and `make start-tablet` do the same.

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

## BIM mode
Run `make bim`, then restart your viewer and press **BIM**. The scan is replaced by a simulated
model: estimated walls and floor, plus one IFC element per detected object. **Look** cycles through:
- **Real**: each object's own scanned splats, in true colour and full detail, in the clean room.
- **Mesh**: a mesh built from those same splats, coloured by IFC class. This is also the shape in
  `model.ifc`, so it follows the real object instead of a box.
- **Box**: simple shapes, coloured by IFC class: fitted boxes and cylinders, or see-through
  bounding boxes where no shape was fitted.
- **Tap an element** to see its IFC class, GlobalId and properties. Equipment also opens the normal
  panel, so **Ask Val**, **Route here** and **Move** still work, and moves show in BIM.
- **Class boxes** hide or show element types. **Isolate** keeps only the selection, walls and floor.
- **Section** cuts everything above a height, like a floor plan. It switches to the Mesh look.
- **Download IFC** saves `model.ifc` (IFC4), which opens in BIM tools such as Bonsai.

It is a simulation, not a survey. Shapes only cover what the scan and the object detection saw:
hidden sides stay open, and a detection that caught only part of an object gives only that part.
Meshes are smoothed 2-4 cm voxels, so thin parts can look bumpy. Walls are the scan's outermost
dense bands, and doors or openings aren't modelled. Tags made by rule or by eye show as `P-005?` and
`IdentityConfirmed: no`.

Objects you move follow in BIM mode. Objects added, split or combined in the viewer show as plain
see-through boxes. With the backend running, **Download IFC** saves the model as it stands now,
including all of those changes, but with simple shapes rather than scan meshes. Without it, you get
the file `make bim` built, which has the scan meshes but none of the changes.

## Move an object
1. Tap the object. The smallest box under your finger is selected.
2. Press **Move**, or **Rotate** to turn it. Only movable objects have these buttons.
3. Drag anywhere on the screen. The object follows your drag across the floor.
4. Release to save. If a route is showing, it plans again.
   - If the spot is taken, the object and whatever's in its way turn red, and the panel says why.
   - Releasing on a red spot puts it back at the last good spot. A wall or fixed equipment blocks it too.
5. **Done**, or Esc, finishes. **Undo changes** in **More** puts everything back.

**Try this first:** the roll cage `obj-0067`. Plan a route with **Go to P-005** from the middle of the room,
then drag the cage onto the route. The route bends around it. To drag from a better view without changing
the route, press **Walk** to switch to **Fly** first.

Every movable object moves as the real scan, including split and combined ones. `obj-0067`, `obj-0021`, and
`obj-0112` are cut in advance by `make pieces`, with the floor behind them patched, so they look cleanest.
Others are cut by their box when you press **Move**, which takes a moment. Anything else in the box
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

## Duplicate or delete an object
Tap an object to find both buttons.
- **Duplicate** puts a copy on a free spot beside it, in the scan and in BIM mode. It's the same object with its
  own ID, named like `P-005 copy 1`. Records and history stay with the original.
- **Name it** names any object with no record link, in labels, Plan, BIM mode and the IFC. A name can't be
  a record's tag, such as `P-005`, because it would look like that device.
- **Delete** asks first, then removes the object from the scan, the routes, BIM mode and the exports.
  **Undo changes** brings it back. It hides the object's whole box, so a neighbour inside it goes too.

## Go back
Esc, or the back button on a phone, goes back one step: it closes **More**, cancels a question or a selection
box, finishes a move, stops a walk, closes Val or Plan, and then deselects the object.

## Add a missed object
1. In **More**, press **Add object**, then drag a box around it or tap it.
2. Check the orange box. Use **Bigger** or **Smaller** if it's off.
3. Check the type and whether it can move. A model suggests these if `make model` has run.
4. Press **Save**. It blocks routes straight away and is marked "new, unconfirmed".

## Split an object that's really two things
1. Tap the object, and under **Fix this object** press **Split into two**. Objects linked to a record can't be split.
2. Drag a box around one part. Orange is what you selected, and blue is the rest.
3. Check the type and whether each can move, then press **Save**. Both are marked "new, unconfirmed".

Split or combine before moving: a moved object has to be put back first, with **Undo changes**.

Set a part to movable to move it, and its real splats go with it. **Undo changes** brings the original back.

## Combine objects that are really one thing
1. Tap the first object, and under **Fix this object** press **Combine with...**. Objects linked to a record can't be combined.
2. Tap the second object. An orange box appears around both.
3. Check the type and whether it can move, then press **Save**. **Undo changes** brings the originals back.

## See the floor layout
Press **Plan** for the room from above: walls, objects by type, the route, and an arrow showing where you are.
Colours match BIM mode, and a dashed outline means the object can be moved.
- **Find:** type a tag or type. `P-005` highlights one object, and `tank` highlights them all.
- **Tap an object** to open its panel, then use **Route here**.
- **Show pipes** adds pipes, which are hidden to keep it readable.
- **Download DXF** saves the layout for CAD tools, with objects where they stand now.

It's generated from the scan, not surveyed: objects are boxes, and the scale hasn't been checked on site. A name
with no room to show stays hidden until you find or tap its object. Needs `make api` and `Equipment Room.ply`.

## Ask Val
Val is the field-service assistant. Press **Ask Val**, with or without an object selected, then type or tap a
suggestion. It can say what needs attention, what's wrong with a device, what to check next and when it was
last serviced, and it can take you there by drawing the route. **× ** beside "About ..." stops asking about
that object.

Val answers from the plant's records straight away. With a language model running, its summary appears below as
"In plain words" when it's ready, about 10 seconds on a ThinkPad, and only if code's checks pass. **How Val
knows** shows what's recorded, possible causes, confidence and how it was worded. Val says when it has no
records on something, doesn't guess which device an unlinked object is, and refuses to operate equipment.

## Other controls
The main buttons are **Go to P-005**, **Plan**, **Ask Val** and **More**, with **Walk route** and **Clear route**
while a route shows. Everything else is in **More**.

| Control | What it does |
|---|---|
| **Go to P-005** | Plans a route to the faulty device from where you stand. Arrows show the way |
| **Movement: Walk / Fly** | In **Walk** the route starts from wherever you move to. In **Fly** you can look around from anywhere, and the route keeps its start |
| **Walk route** | Walks the route, and stops looking at the device |
| **Route for: Person / Robot** | Changes the body size and height for routes |
| **Plan** | Shows the floor layout from above |
| **Range** | How far away frames and labels show |
| **Boxes on** | Shows or hides frames |
| **View: Scan / Both / Objects** | The real scan, fitted shapes over it, or shapes only |
| **BIM** | Simulated BIM model of the room, with IFC properties. Needs `make bim` |
| **Apart** | Pulls objects apart to show them separately |
| **Phone** | Turn the device to look, and walk to move. Needs `make web HTTPS=1` |

## If it's slow
The viewer helps itself: it stops redrawing while nothing changes, lowers the resolution while moving if the
device can't keep up and sharpens when you stop, and uses the light scene on anything without a graphics card.
These go in the URL:
- `?res=0.5` draws fewer pixels. `?lod=0&res=2` is the sharpest.
- `?scene=light` or `?scene=full` chooses the scene.
- `?adaptive=0` keeps the resolution fixed. `?debug=1` shows the frame rate.

On a laptop, use `./start laptop`: objects are cut from the light scene, which `./start browser` doesn't do.

## If something's wrong
| What you see | Why | Fix |
|---|---|---|
| "Backend not connected" | `make api` isn't running | Start it. Check http://localhost:8001/docs |
| "Backend has different objects" | `make web` and `make api` use different files | Pass `ASSETS=data/scene/equipment_room/assets_mapped.json` to `make web` |
| `make api` fails on a missing file | `make mapping` hasn't run | Run `make scene mapping` |
| No **Move** button | The object is fixed or unsure | The panel says which. Try `obj-0067` |
| Box goes red and panel says "Can't place it here" | That spot is taken | Drop it somewhere else. Tiny overlaps are allowed, because boxes are loose |
| Route jumps or disappears as you look around | You're in Walk mode, so it starts from where you are | Press **Walk** to switch to **Fly**, then **Go to P-005** again |
| Only an outline moves | The backend couldn't cut it | Check `make api` is running and `Equipment Room.ply` is in place |
| Object moves, but no route change | No route showing, or it isn't in the way | **Go to P-005** first, then drag onto the line |
| "Couldn't save the move, so it went back" | The backend refused it, so the object returned to where the backend has it | The message says why. Try another spot |
| "Couldn't save the change, trying again" | The backend can't be reached. Routes ignore the change until it's saved | Start `make api`. The viewer sends it once it's back |
| "Couldn't add an object: Selecting needs the scene" | `Equipment Room.ply` is missing | Put it in `data/scene/equipment_room/` |
| "No route to..." | Something blocks the way | That can be correct. **Undo changes** if you caused it |
| "The backend lost saved moves" | `make api` restarted with no database, which it does whenever a `.py` file in the repo changes. Or someone pressed **Undo changes** on another screen | Run `make db` before `make api` to keep moves across restarts |
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
Every button has a command, so a voice assistant can do the same things. `GET /api/viewer/actions` lists them.
```bash
curl -X POST localhost:8001/api/viewer/commands -H 'Content-Type: application/json' \
  -d '{"action": "route_to", "args": {"object_id": "obj-0049"}}'
```
The open viewer runs it within about half a second. `GET /api/viewer/commands/ID` shows the result. Adding,
splitting, and combining only start from a command, because a person draws or taps the rest.

## Val's voice
Val reads its answer aloud with the device's own voice. **Voice on** turns this off. A device with
no voice installed stays silent. Speaking to it isn't built yet: browser speech recognition usually needs
internet, so offline needs a local model such as Whisper.

