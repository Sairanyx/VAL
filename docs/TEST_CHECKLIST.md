# Feature and deliverables checklist

What we have, what works, what we keep, what we add, and what we must hand in. Deadline: **Sunday 8 November,
10:00 Helsinki time**. Editing is allowed until then, so submit early and improve.

**Run it:** `./start laptop` with no graphics card, or `./start browser` with one, then open
http://localhost:8000/?tablet=0. Test on the real scene. Most controls are under **Actions**.

**How to read a line**
- **Tick the box** only when a person has seen it work on the real scene. Everything starts unticked.
- **Built:** ✅ yes, 🟡 partly, ❌ no.
- **Tested:** 🤖 passed a team automated browser or API check, 👤 needs a person, ❌ nothing yet. 🤖 doesn't mean it
  looks right or feels good.
- **Plan:** KEEP, CUT, ADD, or DECIDE. These are suggestions, so change them.
- If something fails, leave it unticked and add it under **Bugs** at the end.

## Who tests what
Pull first, tick only your own part, and push small changes often, so ticks don't collide. Lines with a name in
brackets belong to that person.

| Person | Parts up to and including Setup and pipeline |
|---|---|
| **Eduard** | Val. Scoring: navigation, backend. Setup: database, nav-check, `./start` |
| **Viktor** | Changing objects. Plan. Setup: scene, pieces, highlights, BIM, pipeline, video to splat, updates |
| **Sasha** | Selecting an object. BIM. Scoring: extraction. Setup: LiDAR decision |
| **Hannu** | Routes and nearby, Saving, Backend commands. Scoring: AI diagnostics. Setup: mapping, language models |
| **Benjamin** | Main buttons, Actions menu, Tablet and speed. Scoring: demo |
| **Everyone** | `make setup`, `make check` on your own machine |

## Must work: Valmet's scoring
- [ ] (Sasha) **Extraction, 30%:** objects framed in the scene. ✅ 🤖 KEEP. Count them, and score the 60-object sample
- [ ] (Eduard) **Navigation, 25%:** collision-free route to the fault, with nearby objects shown. ✅ 🤖 KEEP
- [ ] (Hannu) **AI diagnostics, 20%:** Val explains the fault using records and sources. ✅ 🤖 KEEP. Score the 60 questions
- [ ] (Eduard) **Backend, 15%:** one automated pipeline, clean code. 🟡 ❌ KEEP. `make pipeline` has only had a dry run
- [ ] (Benjamin) **Demo, 10%:** clear, reliable, easy to understand. ✅ 👤 KEEP. Rehearse it

## Main buttons
**Who: Benjamin**

- [ ] **Go to P-005:** route to the faulty device. ✅ 🤖 KEEP
- [ ] **Map:** blueprint from above, equipment with a record only. ✅ 🤖 KEEP
- [ ] **Ask Val:** opens the assistant. ✅ 🤖 KEEP
- [ ] **Actions:** opens the other controls. ✅ 🤖 KEEP
- [ ] **Walk route:** walks the route and ends facing the device. ✅ 🤖 KEEP
- [ ] **Clear route:** removes the route. ✅ 🤖 KEEP

## Actions menu
**Who: Benjamin**

- [ ] **Movement, Walk or Fly:** at floor level, or free. ✅ 🤖 KEEP
- [ ] **Back to start:** returns to the start point. ✅ 👤 KEEP
- [ ] **Route for, Person or Robot:** changes body size. ✅ 🤖 KEEP
- [ ] **Phone:** turn to look, step to walk. Needs HTTPS. ✅ ❌ DECIDE after the tablet test
- [ ] **Track:** follows the device with ARCore. ✅ ❌ DECIDE. Cut if it doesn't work on the Lenovo
- [ ] **View, Scan, Both or Objects:** scan, shapes, or both. ✅ 🤖 KEEP
- [ ] **BIM:** opens the BIM model. ✅ 🤖 KEEP
- [ ] **Boxes on or off:** shows or hides frames. ✅ 🤖 KEEP
- [ ] **Range:** 2, 3, 5 or 10 m for frames and labels. ✅ 🤖 KEEP
- [ ] **Apart:** pulls objects apart, Valmet's extra credit. ✅ 🤖 KEEP
- [ ] **Add object:** draw a box around something missed. ✅ 🤖 KEEP
- [ ] **Reset all:** back to the original scan. ✅ 🤖 KEEP

## Selecting an object
**Who: Sasha**

- [ ] **Tap to select:** nearest object wins, never one behind it. ✅ 🤖 KEEP
- [ ] **Hover outline:** shows what a click would pick, with a mouse. ✅ 🤖 KEEP. Check the frame rate
- [ ] **Cyan highlight:** the selected object's surface lights up. ✅ 🤖 KEEP
- [ ] **Details panel:** type, status, telemetry, alarms, documents. ✅ 🤖 KEEP
- [ ] **Dashboard:** charts for a linked object, e.g. P-005. Esc closes it. ✅ 🤖 KEEP
- [ ] **Procedural label:** guessed Excel links are marked. ✅ 🤖 KEEP
- [ ] **No invented IDs:** objects with no record say so. ✅ 🤖 KEEP
- [ ] **Ask Val** in the panel: asks about this object. ✅ 🤖 KEEP
- [ ] **Route here:** route to this object. ✅ 🤖 KEEP
- [ ] **Esc or phone back:** goes back one step. ✅ 🤖 KEEP

## Routes and nearby
**Who: Hannu**

- [ ] **Route avoids obstacles:** never through walls or equipment. ✅ 🤖 KEEP. 383 of 384 passed
- [ ] **Live updates while walking:** every 0.1 m. ✅ 🤖 KEEP. Check it isn't jumpy
- [ ] **Live updates while dragging:** route changes before you drop. ✅ 🤖 KEEP
- [ ] **Flowing arrows:** show the way. ✅ 👤 KEEP
- [ ] **Clear "no route" reason:** says why. ✅ 🤖 KEEP
- [ ] **Nearby objects during the walk:** show status. ✅ 🤖 KEEP
- [ ] **Faults along the way:** the brief wants normal devices on the path. 🟡 👤 DECIDE. The room is small
- [ ] **Real start point:** an actual entrance. ❌ ❌ ADD. It's only the scene's default now

## Changing objects
**Who: Viktor**

- [ ] **Move:** drag on the floor. Movable objects only. ✅ 🤖 KEEP
- [ ] **Rotate:** drag, ↶ 45°, ↷ 45°, or two-finger twist. ✅ 🤖 KEEP. Two-finger twist untested
- [ ] **Done:** ends moving, and doing something else ends it too. ✅ 🤖 KEEP
- [ ] **Collision warning:** both go red, and it returns to the last good spot. ✅ 🤖 KEEP
- [ ] **Clean move, three objects:** `obj-0067`, `obj-0021`, `obj-0112`. ✅ 👤 KEEP. Use these in the demo
- [ ] **Other objects:** cut by their box, which can take neighbours along. 🟡 👤 KEEP, but avoid in the demo
- [ ] **Floor under moved objects:** copied, not scanned. 🟡 👤 KEEP. Say this honestly
- [ ] **Duplicate:** a copy on a free spot, named `P-005 copy 1`. ✅ 🤖 DECIDE. Not requested by Valmet
- [ ] **Delete:** asks first. ✅ 🤖 KEEP. Known issue: it hides the object's whole box
- [ ] **Name it:** for objects with no record. ✅ 🤖 KEEP
- [ ] **Split into two:** ✅ 🤖 KEEP
- [ ] **Combine with...:** refused if linked or moved. ✅ 🤖 KEEP
- [ ] **Add object suggestions:** a vision model suggests a label. 🟡 👤 DECIDE. Needs a model running
- [ ] **Old spot unblocks after a move:** known issue, it can stay blocked. 🟡 ❌ ADD a fix

## Saving
**Who: Hannu**

- [ ] **Saved at once:** about 14 ms when you let go. ✅ 🤖 KEEP
- [ ] **Survives a restart:** API and database. ✅ 🤖 KEEP
- [ ] **Reload restores changes:** ✅ 🤖 KEEP
- [ ] **Database down:** app keeps working, and saves when it's back. ✅ 🤖 KEEP
- [ ] **Telemetry in TimescaleDB:** 4,320 readings. ✅ 🤖 KEEP
- [ ] **Val reads telemetry from TimescaleDB:** it still reads Excel. ❌ ❌ DECIDE. Needed for simulated data
- [ ] **Simulated machine data and diagnostics:** ❌ ❌ DECIDE. You parked this

## BIM and Plan
- [ ] (Sasha) **Real, Mesh, Box looks:** ✅ 🤖 KEEP
- [ ] (Sasha) **Show or hide types:** ✅ 🤖 KEEP
- [ ] (Sasha) **Section cut:** ✅ 🤖 KEEP
- [ ] (Sasha) **Isolate:** ✅ 🤖 KEEP
- [ ] (Sasha) **IFC properties on tap:** ✅ 🤖 KEEP
- [ ] (Sasha) **Download IFC:** 0 schema issues. Not opened in a real BIM tool. ✅ 🤖 KEEP. Live file has boxes only
- [ ] (Sasha) **Moves and turns follow in BIM:** ✅ 👤 KEEP. Turning in BIM untested
- [ ] (Sasha) **Leaving BIM is clean:** no ghosts or leftovers. ✅ 🤖 KEEP
- [ ] (Viktor) **Plan search:** `P-005` or `tank`. ✅ 🤖 KEEP
- [ ] (Viktor) **Plan tap:** opens the object. ✅ 🤖 KEEP
- [ ] (Viktor) **Download DXF:** not opened in a real CAD tool. ✅ 🤖 KEEP
- [ ] (Viktor) **Plan's scale:** not checked on site. 🟡 ❌ KEEP. Say it's generated

## Val
**Who: Eduard**

- [ ] **Talking to Val:** press the mic or **V**, speak, and it stops by itself. Runs on our server with no internet. Works in a browser with spoken test audio. ✅ 🤖 KEEP. Try a real voice and the tablet's mic, in a noisy room
- [ ] **Val doing actions:** say or type it, like "Hide the frames" or "Delete it". The wording can vary, and it only acts on what's selected or named. ✅ 🤖 KEEP
- [x] **Instant answer from records:** ✅ 🤖 KEEP
- [x] **"In plain words":** model summary, about 10 s on a ThinkPad. ✅ 👤 KEEP. Gemma's answers are terse
- [ ] **What needs attention:** ranks devices by urgency, then health. Automated check passes, so check the ranking makes sense. ✅ 🤖 KEEP
- [x] **What's wrong, what to check, last service:** with sources. ✅ 🤖 KEEP
- [ ] **Make path:** the new name for "Take me there". It draws the route, and **Walk route** does the walking. ✅ 🤖 KEEP
- [x] **Follow-up questions:** "it" stays on the same machine. ✅ 🤖 KEEP
- [x] **Suggestions:** fit what's selected. ✅ 🤖 KEEP
- [x] **How Val knows:** evidence, causes, confidence. ✅ 🤖 KEEP
- [x] **Doesn't guess:** no records means it says so. ✅ 🤖 KEEP
- [ ] **Safety refusal:** "Shut down", "Close CV-003", "Isolate" and others now get "I can't do that". ✅ 🤖 KEEP. Hannu, this changes your rule, so please check it
- [ ] **Safety refusal, false alarms:** "What does drain mean?" now gets its own reply, and "Stop walking" still works. ✅ 🤖 KEEP
- [ ] **Unclear or off-topic messages:** Val says "Sorry, I don't understand that". ✅ 🤖 KEEP
- [ ] **Typing in Val's chat:** W, A, S and D stay in the chat and don't move the view. ✅ 🤖 KEEP
- [x] **Gemma on a ThinkPad:** `./start laptop`. ✅ 👤 KEEP
- [ ] **60-question copilot test:** `scripts/eval_copilot.py`. 56 of 60 met their expected result. The other 4 fell back to the records. ✅ 👤 KEEP. A person still has to read and score the answers

## Tablet and speed
**Who: Benjamin**

- [ ] **Tablet layout:** tap a window to close it, no X, big buttons. ✅ 🤖 KEEP
- [ ] **Light scene on phones and tablets:** automatic. ✅ 🤖 KEEP
- [ ] **Stops redrawing when still:** and sharpens when you stop. ✅ 🤖 KEEP
- [ ] **Load time is acceptable:** known not improved. 🟡 👤 Measure it
- [ ] **Real Lenovo, real frame rate:** ❌ ❌ ADD. Must test. Chrome 81 can't run it
- [ ] **Joystick:** moves you on touch screens. ✅ ❌ KEEP
- [ ] **Connects over the local network:** HTTPS and firewall. ✅ ❌ KEEP
- [ ] **VR mode, video with a faint twin:** ❌ ❌ DECIDE. You parked this. Not in the scoring
- [ ] **Pre-made 3D models for nearby objects:** ❌ ❌ DECIDE. Parked, with the VR mode

## Backend commands
**Who: Hannu**

- [ ] **Every viewer action as a command:** `POST /api/viewer/commands`. ✅ 🤖 KEEP
- [ ] **Action list:** `GET /api/viewer/actions`. ✅ 🤖 KEEP
- [ ] **New actions have commands:** Duplicate, Delete, Name it. ✅ 👤 KEEP. Plan has no command yet: ADD
- [ ] **Health check:** `GET /api/health`. ✅ 🤖 KEEP

## Setup and pipeline
- [ ] (Everyone) `make setup`: ✅ 👤 KEEP
- [ ] (Viktor) `make scene`: objects, floor map, light scenes. ✅ 👤 KEEP
- [ ] (Hannu) `make mapping`: links 30 Excel records. ✅ 🤖 KEEP
- [ ] (Viktor) `make pieces`, `make highlights`, `make bim`: ✅ 👤 KEEP
- [ ] (Eduard) `make db`: ✅ 🤖 KEEP
- [ ] (Hannu) `make laptop-model`, `make model`: ✅ 👤 KEEP
- [ ] (Everyone) `make check`: 267 passed on main. ✅ 🤖 KEEP
- [ ] (Eduard) `make nav-check`: ✅ 🤖 KEEP
- [ ] (Eduard) `./start browser`, `laptop`, `tablet`: ✅ 🤖 KEEP
- [ ] (Viktor) `make pipeline`, for real on a GPU machine: 🟡 ❌ KEEP. Masks need a SAM setup, as Roihu is closed
- [ ] (Viktor) **Video to splat:** frames, COLMAP, training. By hand. 🟡 🤖 KEEP for new rooms only
- [ ] (Sasha) **LiDAR input:** ❌ ❌ DECIDE. Pitch it as future work
- [ ] (Viktor) **Update by short clip, or by rescan:** ❌ ❌ Pitch as future work

## Clean up
Only after the rehearsal, and only if tests pass.
- [ ] **Second extraction route:** `app/extract/masks`, `merge`, `label`. CUT or retire
- [ ] **Old code:** `app/scene/cluster.py`, `split.py`. CUT once confirmed unused
- [x] **Starter template:** `app/train.py`, `make train`, `make up`, the GPU check and LUMI jobs. Removed
- [ ] **Own-splat and Roihu scripts:** KEEP, marked for new rooms only
- [ ] **Stale handoffs:** Benjamin and Hannu to update theirs

## Laptop rehearsal, internet off
- [x] The zip unzips and runs from an empty folder on Linux, first run about 20 s, later starts 3 s (Viktor)
- [ ] The zip runs on Windows, with the double-click: not tried, nobody's tested it on Windows yet
- [ ] The zip runs on a Mac, with right-click Open: not tried
- [ ] The demo laptop runs it with the internet off, and nothing tries to reach the internet
- [ ] The mic works with a real voice, in a noisy room
- [ ] A second detour is picked, with a route change you can show
- [ ] Full restart time is written down

## New viewer features
- [x] Minimap in a corner on a computer, toggled on a phone, opens to the full map (Viktor)
- [x] Filters narrow frames, labels, the list, the map and BIM, and work by voice (Viktor)
- [x] Plain alerts, chosen by severity, gone outside the real view (Viktor)
- [x] Focus flies to an object's best view, from the list, the panel and by voice (Viktor)
- [x] View goes through darkness, simple BIM, blob BIM, point cloud, real view (Viktor)
- [x] Tutorial, Watch and Try it with Show me, runs start to finish and puts everything back (Viktor, testing Benjamin's)
- [x] IFC: whole, shown and selected downloads hold the right objects (Viktor, testing Benjamin's)
- [x] Walking the route ends with Val starting by itself at the fault (Viktor)
- [x] Val moves objects by measure, and next to other objects (Viktor)
- [x] Glowing, pulsing alerts are back (Viktor)
- [x] Arrow keys move and turn an object only in those modes, and ? shows help (Viktor)
- [ ] Someone other than Viktor tries all of these

## The demo, start to finish
- [ ] Open the room: frames show around objects
- [ ] Tap an object: details show
- [ ] Navigate: route and walk work, and nearby objects show status
- [ ] Reach `P-005`: Val starts by itself, with sources and safe checks
- [ ] Move an object: it stays real, and the route changes
- [ ] Undo: everything goes back
- [ ] It runs through 3 times with no problems
- [ ] Valmet or a person confirms which object is `P-005`

## Deliverables: required on the form
Submit at sinceai.app. Any member can submit, and it stays editable until the deadline.
- [ ] **Project name:** not chosen yet
- [ ] **Tagline:** one sentence, 140 characters at most. Voters read this first
- [ ] **About the project:** problem, solution, how we built it, challenges, what's next. 5,000 characters at most
- [ ] **Built with:** comma-separated. The first five show on the vote card
- [ ] **Repository:** `https://github.com/Sairanyx/Newbies`. It's private, so judges use the zip
- [ ] **Demo video:** public or unlisted YouTube, or an MP4 or WebM up to 512 MB. Ideally under 2 minutes
- [ ] **Working in the first 20 seconds:** voters watch it on the vote card
- [ ] **Source code `.zip`:** as at the deadline, up to 250 MB, with no dependencies or data files
- [ ] **Technology feedback:** name the technology, with one or two sentences
- [ ] **GenAI tools used:** tick Anthropic, Hugging Face, Gemma, and add Qwen under Other. Check with the team
- [ ] **Did we implement a generative AI model:** yes, say how and why. Local language models word Val's answers
- [ ] **Terms accepted:** the team owns it, and Valmet can use it in its business
- [ ] **Submitted, and every link checked:** open the video logged out

## Deliverables: Valmet's brief
- [ ] **Working demo:** runnable locally, or clearly recorded
- [ ] **Repository README:** concise, with setup steps that work on a clean machine
- [ ] **5–8 slides:** extraction pipeline, pathfinding, Excel mapping, AI approach
- [ ] **Backend slide:** Eduard
- [ ] **Extraction slide and technical note:** Sasha
- [ ] **AI slide:** Hannu
- [ ] **Slide deck owner and video:** Benjamin
- [ ] **Short video, 5 minutes at most:** the route walked from the operator's view, nearby objects framed, fault diagnosed
- [ ] **Technical note:** models, libraries, components
- [ ] **Only measured numbers:** from `docs/RESULTS.md`
- [ ] **Say it accurately:** see "Say this accurately" in `docs/PLAN.md`. Position is simulated, links are procedural
- [ ] **Pre-existing work:** README section is correct
- [ ] **Repository is ready for judges:** follow `docs/ENTIRE.md` before making anything public

## Deliverables: optional on the form
- [ ] **Demo URL:** skip. It runs on a laptop, and hosting Valmet's data needs their OK
- [ ] **Demo zip for judges:** `make bundle`, by link, once Valmet says it's fine. Too big and data-filled for the source `.zip` field
- [ ] **Pitch deck file:** PDF or PowerPoint up to 100 MB. Voters can open it. KEEP
- [ ] **Supporting document:** pilot plan or continuation plan, up to 100 MB. ADD. Fits `docs/PLAN.md`'s rollout
- [ ] **Partner technologies:** tick CSC / LUMI AI Factory, as Roihu did the processing. Check that it counts
- [ ] **Schools of team members:** if anyone is studying
- [ ] **Domain name:** none, skip

## Optional awards
Entering never affects the Valmet entry.
- [ ] **Best Use of Entire:** projector. KEEP: we use it. Show repository or session evidence, and token numbers
- [ ] **Best Use of Tiger Data:** Stream Deck Mini. KEEP: TimescaleDB holds telemetry and changes. Ask if self-hosted counts
- [ ] **Best Use of Gemini API:** DECIDE. Not used, and cloud breaks the on-site rule
- [ ] **Best Use of ElevenLabs:** DECIDE. Not used, and cloud breaks the on-site rule
- [ ] **FIWARE Open Innovation:** skip unless NGSI-LD is really built in
- [ ] **Red Hat OpenShift AI:** skip, not used
- [ ] **Solana, Vultr, Snowflake, MongoDB Atlas:** skip, not used

## Bugs
Write them like this: `- [ ] Section: what you did, what happened, who's fixing it`
- [ ] Undo: a route check failed once, showing 4.69 m. Passed in every run since. Looks like test timing, not proven. Viktor
- [ ] Delete: hides a few small boxes around the object's own splats, so far fewer neighbours go (21% fewer other splats hidden overall). Objects made in the viewer still use their whole box. Viktor
- [ ] Move: a moved object's old spot can stay blocked. Eduard
- [ ] Load time: 6.5 s with the light scene against 10.5 s with the full one, on the laptop with no backend. The full scene is no faster. Viktor
