# Devlog

How this was built, from the commit history. Since AI Hackathon, 6-8 November 2026, Turku, for
Valmet's Industrial Metaverse challenge. Numbers come from [RESULTS.md](RESULTS.md), times from
the commits, so they are rough. Five people, each working with coding agents, on small branches.

## Before the event (4 Nov)
Eduard set up the repo: training template, GPU check, LUMI jobs and Docker. It's listed under
"Pre-existing work" in the README. None of it is the product, and it was removed on the last morning.

## Friday: the plan and a first look (6 Nov, afternoon to midnight)
We wrote down how people and agents share the repo (`AGENTS.md`, a handoff file per person) and read
the brief closely. Two things shaped everything after:
- Valmet's supplied `Industrial Boiler Room.ply` was damaged: 67% of its records look like random
  bytes. Valmet's replacement, `Equipment Room.ply`, is the one we use.
- We chose to make the demo work on site with no internet, because plant data shouldn't leave the
  plant. The brief doesn't ask for this. So no cloud APIs at runtime.

By midnight we could load the scene and render views from it, and Benjamin had a first-person web
viewer running offline with three.js and Spark.

## Overnight into Saturday: from a scan to something that knows things (7 Nov, 00:00 to 07:00)
Everything had to exist at once, so we built the pieces side by side against a shared fixture.
- **Extraction (Viktor, Sasha):** SAM 3 and SAM 2 masks on rendered views, lifted to 3D. First run:
  441 objects, but weak labels, with 251 "pipe" and 0 "pump". Better labels came from vision models.
- **Navigation (Eduard):** a floor map with clearance per body size, then A*.
- **Records (Hannu, Eduard):** the Excel pack linked to objects, and a first copilot, connected to
  the API. Safety rules were in from the start.
- **Storage (Eduard):** TimescaleDB for telemetry and changes, with the demo still working without it.

**What we got wrong.** We cleaned the scene first, which left black holes, so we retracted the
comparison and went back to the uncleaned scene. Cropping objects from the real video frames didn't
line up well enough at object scale, so we removed it. We trained our own splat (3.2 M splats, 25 min)
and compared it by eye: Valmet's looked better, so that's what we show.

**The copilot's rule.** Local models word the answer, but code checks every fact against the records.
We measured prompt changes, and reverted one that lowered accuracy.

## Saturday morning: objects you can actually move (09:00 to 14:00)
Valmet's engineer said objects you can pull out and move would earn extra credit, so we made it real:
dragging moves the object's own splats, nearby floor is cloned under it, and routes re-plan live.
Then came the rest of what a person needs: moves onto something solid are refused, missed objects can
be added, and wrongly grouped ones split or combined. Links are marked uncertain with a "?", because
29 of 30 are procedural, and we don't invent identity. Sasha added cyan highlights on the object's
real surface.

## Saturday afternoon: BIM and a map (14:00 to 18:00)
Sasha added a simulated BIM model with an IFC4 export, first as boxes, then with real scanned objects
and scan meshes. Viktor added a floor plan and DXF export, and IFC with the operator's changes in it.
Eduard added commands for every viewer action, a tablet mode, and one-command start scripts.

## Saturday evening: making it usable (17:30 to 21:00)
We showed it to the engineer. The viewer needed heavy optimization and a better UI, and Val's
functionality was heavily emphasized. So:
- **Speed:** stop redrawing when nothing changes, a light scene without a graphics card, and pieces
  cut in advance. On a ThinkPad with integrated graphics: 16 frames a second turning, 59 standing still.
- **Simpler:** the copilot became Val, and talks like a person. Buttons moved into one menu. Benjamin
  added keyboard shortcuts, undo, and an Objects panel listing equipment by importance.
- **Voice:** Eduard added local Whisper, so you can talk to Val and it can run viewer commands, with
  no cloud. Hard refusals for anything that operates the plant.

## Saturday night: robust, clear, and runnable by someone else (21:00 onwards)
We compared the project against the brief line by line, which found two real gaps:
- The diagnosis didn't start when the worker arrived. Now it does.
- Nobody could see a worker, because the walk was first-person. We tried a figure walking ahead, then took it
  out again: the camera is the operator's own view, and the minimap shows where they are.

Also from the fix list: Val can move things by measure, like "2 metres left" or "next to the other chair".
Benjamin's glowing, pulsing alerts came back after we'd toned them down too far. filters that narrow frames, labels, the list, the map and BIM at once, and by
voice. Plain alerts in place of glowing ones. A see-through minimap, with the full map on a click.
Focus, which flies to an object's best view. One control through darkness, simple BIM, blob BIM, point
cloud and the real view. A guided demo button, arrow keys for moving objects, and a help panel.

**The zip.** The target changed from our GPU server to a judge's laptop. `./start` wouldn't run there:
it needs bash and make, installs the training stack, and doesn't allow a Mac. So `make bundle` builds a
zip with its own uv and a light environment: unzip, double-click, and it opens. Testing it from an empty
folder caught a missing package that our own machines were hiding. Weak graphics get a one-way
drop in resolution, which took turning on that ThinkPad from about 14 to about 50 frames a second.

## Still open at the time of writing
See "How we cover the brief" in [CHALLENGE.md](CHALLENGE.md) and the [checklist](TEST_CHECKLIST.md).
