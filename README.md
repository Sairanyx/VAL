# VAL: Valmet Asset Locator

> A virtual twin of the plant room, where Val finds the faulty device, routes you there safely,
> and explains the fault from the records.

Team Newbies, Since AI Hackathon 2026, for Valmet's Industrial Metaverse challenge.

## The problem
When a pump starts failing in a plant room, the technician sent to fix it has to work out several
things before touching anything. Where exactly is it? What's around it? What has gone wrong before, and
what does the service history say? What's safe to do? That knowledge is spread over drawings, the
control system, maintenance records and manuals, and the room itself is cramped, full of pipes, carts
and things that have moved since anyone last drew it.

A 3D scan captures the room as it really is, but a scan is just a picture you can walk through. It
doesn't know that the red thing in the corner is pump P-005, that it's been losing efficiency for a
week, or how to get to it without walking through a tank. And the companies running these plants
usually don't want their data going to a cloud service to find out.

## What we built
VAL turns Valmet's scan of an equipment room into a twin that does know those things. It finds the
objects in the scan, links them to Valmet's equipment records, works out where you can walk, and takes
you to the device that needs attention.

Its assistant is **Val**: a field-service copilot you can type or talk to. Val answers from the plant's
own records, always says where an answer came from, and suggests safe checks. It never operates the
plant. Everything, Val included, runs on one laptop with no internet, so the plant's data never leaves
the site.

### Every object, framed
VAL finds 440 objects in the scan and draws a frame around each one, coloured by type. Equipment with a
record shows its condition and health. Equipment that needs attention glows as you approach it. You can
filter by type or condition, or open a list of equipment sorted by what needs attention first.

![Filters and the equipment list](docs/images/find.jpg)

### From a simple model to the real room
The same room can be shown five ways: dark, a simple BIM model of fitted shapes, a rougher model built
from the scan's surfaces, the raw point cloud, and the real scan. Press the **B** key, or ask Val to
"show the point cloud". The BIM model exports to IFC for CAD and BIM tools.

![The simple BIM, the blob BIM, the point cloud and the real scan](docs/images/views.jpg)

### Getting to the fault
**Go to critical** plans a route to the device that needs attention most, around walls, machines and
anything that has been moved. A small map in the corner shows where you are and where you're going.
Walking the route, the equipment you pass shows its frame and status.

![A route from the entrance to the critical pump](docs/images/route.jpg)

### Val explains it
When you arrive, Val opens by itself and explains the fault: health, likely cause, what to check first,
and the safety steps, with the record IDs it used. You can ask more: when it was last serviced, how its
sensors are trending, what the guidance says. Val also controls the view: "show only pumps", "take me to
P-005", "move the cart 2 metres left".

![Val explaining the fault on arrival](docs/images/val.jpg)

Each device's full record can also be opened as a dashboard of charts.

![A device's dashboard](docs/images/dashboard.jpg)

### Changing the room
Rooms change, so objects can be moved, turned, copied, split, combined or deleted, with the mouse,
the arrow keys, touch or by asking Val. The scanned object itself moves, not just its frame, and the
route goes around it. Every change can be undone.

A tutorial runs on the first visit: watch it play through, or try each step yourself.

## How it works
1. **Finding objects.** We render hundreds of views of the scan, cut each view into object masks with
   SAM, and combine the masks across views into 3D objects. A local vision model names each object, and
   we checked the names against screenshots.
2. **Linking records.** Valmet's records don't say where each device is, so each record is placed on an
   object of the right kind, as the challenge allows. Every link is marked as unconfirmed, with a "?"
   after the name.
3. **Routes.** A floor map is built from the scan, showing where a person or a small robot fits. Routes
   are planned with A* and updated when objects move.
4. **Val.** Code looks up the facts in the records and checks every ID and number. A small language
   model running on the laptop only puts them into words.
5. **The app.** A Python backend (FastAPI) and a browser viewer (three.js with Spark for the scan).

Code: [`app/extract`](app/extract) finding objects, [`app/nav`](app/nav) routes,
[`app/copilot`](app/copilot) Val and the record links, [`app/api`](app/api) the backend,
[`web`](web) the viewer.

## Results
- 440 objects found in the scan.
- 20 of Valmet's 30 records linked, each to an object of the right kind. All six pumps sit on pumps.
- A route to any of the 440 objects for a small robot, and to 384 for a person; the rest are out of a
  person's reach.
- Val met the expected answer on 56 of 60 test questions, and refused everything it should.
- Speech recognised correctly 9 times out of 10, with background noise.

Full measurements: [`docs/RESULTS.md`](docs/RESULTS.md).

## Running it
```bash
make demo
```
The first run downloads Valmet's scan and Excel pack, installs only what the demo needs (no PyTorch,
no GPU) and builds everything, which needs internet; after that it starts straight away, offline.
Open the address it prints. To run the extraction pipeline itself on a new scan, use `make pipeline`,
which installs the full stack and needs an NVIDIA GPU. For another
laptop, `make bundle` builds a zip that sets itself up on first run. Details:
[`docs/USAGE.md`](docs/USAGE.md).

## Limits
- The record links are placed by type, not confirmed. Even P-005 is our best guess.
- Object names were checked from screenshots by a coding agent, not by a person.
- The sensor data is a sample from the records, not live.
- The technician's position is simulated: the camera is the technician.

## More
[Usage](docs/USAGE.md) · [Architecture](docs/ARCHITECTURE.md) · [Results](docs/RESULTS.md) ·
[How it was built](docs/DEVLOG.md) · [The challenge](docs/CHALLENGE.md)

## Team
Viktor Trilar, Oleksandr Yakovlev, Eduard Rednic, Hannu Kiviranta, Benjamin Sundell

## Pre-existing work
The setup in the first commits was made before the event. Everything after was built at Since AI 2026.
Experiments on Roihu reused Python environments and model weights installed before the event, for
Pi3X and COLMAP.
