# Test checklist

Test on the real scene, not a test scene. Tick a box only when you've seen it work. If it fails, leave it
unticked and add a line under **Bugs** at the end. Start with an empty scene: press **Undo changes**.

**Run it:** `./start browser`, then open http://localhost:8000/?tablet=0

## 1. Setup
- [ ] `make setup` installs with no errors
- [ ] `make gpu` prints the GPU name
- [ ] `make scene` downloads objects, floor map and light scenes
- [ ] `make mapping` links 30 Excel records
- [ ] `make pieces` cuts the movable objects
- [ ] `make highlights` finishes
- [ ] `make bim` writes the model and `model.ifc`
- [ ] `make db` starts the database and loads 4,320 telemetry rows
- [ ] `make model` downloads the language model
- [ ] `make check` passes
- [ ] `make nav-check` passes every check

## 2. Starting
- [ ] `./start browser` starts everything, and prints the address
- [ ] `./start tablet` starts everything, and prints the tablet's address
- [ ] Ctrl+C stops everything, and ports 8000 and 8001 are free
- [ ] `./start` says what's missing if a file is gone
- [ ] `./start` says so if the ports are already in use
- [ ] http://localhost:8001/api/health shows database, copilot and floor map as true
- [ ] The scene loads with no holes in the floor
- [ ] The frame rate is smooth enough to use (write it down)
- [ ] The viewer warns when the backend is off

## 3. Looking around
- [ ] Mouse or touch drag turns the view
- [ ] Walk moves at floor level
- [ ] Fly moves freely
- [ ] **Start** goes back to the start point
- [ ] **Range** changes how far frames and labels show: 2, 3, 5, 10 m
- [ ] **Boxes on/off** shows and hides frames
- [ ] **Scan**, **Both** and **Objects** views each look right
- [ ] **Apart** pulls objects apart, and **Together** brings them back
- [ ] Labels don't overlap too much to read
- [ ] Frames behind nearer objects stay hidden

## 4. Objects
- [ ] Tapping an object selects it, and picks the smallest box under your finger
- [ ] The selected object's surface turns cyan
- [ ] Selecting another object moves the highlight
- [ ] The details window shows type, status, telemetry, alarms and documents
- [ ] Linked objects show their Excel record, marked as procedural
- [ ] Objects with no record say so, with no invented ID
- [ ] The close button closes the window

## 5. Routes
- [ ] **Go to P-005** draws a route on the floor
- [ ] **Route here** draws a route to the selected object
- [ ] The route goes around walls and equipment, and never through them
- [ ] It keeps to free floor you could really walk on
- [ ] Arrows flow towards the target
- [ ] Walking updates the route while you move
- [ ] **Person** and **Robot** give different routes where they should
- [ ] An object with no route gives a clear reason
- [ ] **Walk route** walks to the object, and ends looking at it
- [ ] The line behind you disappears as you walk
- [ ] **Stop** stops the walk
- [ ] **Clear route** removes it
- [ ] Nearby objects highlight and show status during the walk

## 6. Moving objects
- [ ] **Move on floor** only shows on movable objects
- [ ] Fixed objects explain why they can't move
- [ ] Dragging moves the real scan, with no outline left behind
- [ ] The floor where it stood looks acceptable
- [ ] Dropping it saves it, and it stays there after a page reload
- [ ] **Done** ends move mode
- [ ] Doing something else, like planning a route, also ends move mode
- [ ] Dragging onto another object turns both red and explains why
- [ ] Dragging onto a wall or fixed equipment also goes red
- [ ] Letting go on a red spot returns it to the last good spot
- [ ] No red stays on screen afterwards
- [ ] A route on screen updates while dragging
- [ ] Dropping an object on the route makes it bend around it
- [ ] Blocking the only way shows a clear "no route" message
- [ ] A moved object's old spot stops blocking routes

## 7. Rotating objects
- [ ] **Rotate on floor** only shows on movable objects
- [ ] Dragging turns it
- [ ] The **↶ 45°** and **↷ 45°** buttons turn it
- [ ] Two-finger twist turns it on a touch screen
- [ ] Shift + drag turns it while moving
- [ ] The real scan, frame and highlight all turn together
- [ ] Turning into something goes red, and returns to the last good angle
- [ ] Quick repeated turns all save, with none lost
- [ ] The angle stays after a page reload
- [ ] Routes use the turned shape

## 8. Add, split and combine
- [ ] **Add object** lets you draw a box around something
- [ ] It suggests a label, and **Smaller** and **Bigger** change the box
- [ ] **Save** adds it, marked as not confirmed
- [ ] **Cancel** adds nothing
- [ ] A new object blocks routes straight away
- [ ] **Split into two** makes two objects
- [ ] **Combine with...** makes one object from two
- [ ] Linked or moved objects are refused, with a clear reason
- [ ] New, split and combined objects can be selected and routed to
- [ ] All of these stay after a page reload

## 9. Undo and saving
- [ ] **Undo changes** puts every moved and rotated object back
- [ ] It removes added objects, and brings back split and combined ones
- [ ] Routes update after undo
- [ ] Changes stay after restarting the API
- [ ] Changes stay after restarting the database
- [ ] Moves made with the database stopped save once it's back
- [ ] The API keeps working with the database stopped
- [ ] Saves feel instant

## 10. BIM
- [ ] **BIM** opens the model, and **Exit BIM** returns to the same view
- [ ] **Real**, **Mesh** and **Box** looks each work
- [ ] Class filters show and hide each class
- [ ] **Section** cuts through at each height
- [ ] **Isolate** shows one object, and **Show all** undoes it
- [ ] Tapping an object shows its IFC properties
- [ ] Moved and rotated objects follow in BIM
- [ ] Moving in BIM follows on return to the scan
- [ ] Added, split and combined objects show correctly
- [ ] No leftover frames or cubes after leaving BIM
- [ ] Routes still work in BIM
- [ ] **Download IFC** gives a file a real BIM tool can open

## 11. Plan view
- [ ] **Plan** opens the floor layout, and **Close** leaves it
- [ ] Search finds a tag or type, such as P-005
- [ ] Tapping an object selects it
- [ ] **Show pipes** shows and hides pipes
- [ ] Moved objects appear at their new spot
- [ ] **Download DXF** gives a file a real CAD tool can open

## 12. Copilot
- [ ] **Copilot** and **Ask copilot** open the window
- [ ] The **Ask** button sends a question
- [ ] "What's wrong with it?" gives the right fault
- [ ] "When was it last serviced?" cites a work order
- [ ] "What should I check?" gives steps, citing a document
- [ ] "Take me to P-005" shows the route
- [ ] Follow-up questions using "it" stay on the same machine
- [ ] Answers show observations, possible causes, sources and confidence
- [ ] An unknown question says it found nothing, and doesn't make things up
- [ ] An object with no record doesn't get another machine's answer
- [ ] "Shut down pump P-005" is refused
- [ ] The local model loads, and answers say **Worded by the local model**
- [ ] If the model fails, it falls back to **Fixed template**
- [ ] An answer takes an acceptable time (write it down)

## 13. Voice
- [ ] Answers are read aloud
- [ ] **Voice on/off** works, and off stops speech at once
- [ ] Closing the window stops speech
- [ ] Refused requests are read aloud too
- [ ] Speaking to the copilot (not built yet)

## 14. Viewer commands
Check these at http://localhost:8001/docs, with the viewer open.
- [ ] `GET /api/viewer/actions` lists the actions
- [ ] Each action works: select, close, route, walk, stop, clear, profile, mode
- [ ] Each action works: boxes, range, view, apart, BIM, reset, copilot
- [ ] Each action works: move, rotate, turn, start move, start rotate, finish, undo
- [ ] Each action works: start add, start split, start combine
- [ ] A bad object or a blocked spot reports a clear error
- [ ] `GET /api/viewer/commands/ID` shows the result

## 15. Tablet
**Run it:** `./start tablet`, then open the address it prints, on the tablet.
- [ ] The tablet reaches the server over the local network
- [ ] The light scene loads, without running out of memory
- [ ] The frame rate is usable (write it down)
- [ ] Windows have no X, and tapping a window closes it
- [ ] Buttons in a window still work, without closing it
- [ ] Windows don't close right after opening
- [ ] Buttons are big enough, and all fit on screen
- [ ] Joystick moves you
- [ ] Touch select, move, rotate and route all work
- [ ] **Phone** mode works with HTTPS: turn to look, step to walk
- [ ] **Track** follows the device with ARCore (check scale by walking a known distance)
- [ ] Copilot answers and speaks on the tablet

## 16. Offline rehearsal on the 5090
- [ ] `make db` and `make api` work on the 5090
- [ ] The 9B model loads, alongside the viewer
- [ ] The router is set up, and the tablet connects
- [ ] Every file and model is on the 5090 first
- [ ] **Internet off:** scene, routes, moves, copilot and voice all work
- [ ] Nothing in the browser tries to reach the internet
- [ ] Restarting everything takes less than a few minutes (write it down)

## 17. Pipeline
- [ ] `make pipeline DRY=1` lists the steps
- [ ] `make pipeline` runs for real on the 5090
- [ ] A failed run continues without redoing finished steps
- [ ] Its objects, floor and routes are as good as the current ones

## 18. The demo, start to finish
- [ ] Open the room: frames show around objects
- [ ] Tap an object: details show
- [ ] Navigate: route and walk work
- [ ] Nearby objects show status on the way
- [ ] Reach `P-005`: the copilot explains it, with sources and safe checks
- [ ] Move an object: it stays real, and the route changes
- [ ] Undo: everything goes back
- [ ] It runs all the way through 3 times with no problems
- [ ] A person has confirmed which object is `P-005`

## 19. Submission
- [ ] Demo video, under 5 minutes, works when logged out of YouTube
- [ ] 5–8 slides
- [ ] Technical note
- [ ] README setup steps work on a clean machine
- [ ] Source `.zip` under 100 MB, with no data
- [ ] Every team member accepts the challenge terms
- [ ] Submitted before Sunday 10:00, then all links checked

## Bugs
Write them like this: `- [ ] Section: what you did, what happened, who's fixing it`
