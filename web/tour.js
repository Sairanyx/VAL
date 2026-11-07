// The tutorial: a guided run through the viewer's features. Each step points at the control it
// explains and says how to use it, by key and by touch.
//
// Two ways through: Watch plays every step by itself, as a showcase. Try it waits for you to do
// each step, with Show me to have it done for you. Both use the same commands as the buttons and
// Val, and put back anything they changed at the end, even if stopped halfway.

const POLL_MS = 100;
const WALK_LIMIT_MS = 60000;
const ANSWER_LIMIT_MS = 12000;
const LEAD_MS = 1400; // in Watch, how long a control is pointed at before it's pressed
const PRAISE_MS = 1600; // in Try it, how long "Done" shows before the next step

export function setupTour({ ui, handlers, press, view }) {
  const state = { running: false, paused: false, mode: null };
  let skip = 0; // each press of Next ends what's being waited for
  let showMe = false; // Try it: Show me was pressed for this step
  let moved = false; // whether there's a move of ours to undo
  let spotTarget = null;
  let spotTimer = 0;
  let changesAtStart = 0; // changes made before the tutorial are never undone by it

  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function wait(ms) {
    const token = skip;
    let left = ms;
    while (left > 0 && token === skip && state.running) {
      await sleep(POLL_MS);
      if (!state.paused) left -= POLL_MS;
    }
  }

  async function until(done, limit = Infinity) {
    const token = skip;
    let left = limit;
    while (left > 0 && token === skip && state.running && !done()) {
      await sleep(POLL_MS);
      if (!state.paused) left -= POLL_MS;
    }
  }

  // ---- Pointing at a control ----

  function shown(element) {
    if (!element) return false;
    const box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== "hidden";
  }

  // A control in the closed Actions menu is pointed at through the Actions button.
  function spotElement() {
    const target = typeof spotTarget === "function" ? spotTarget() : $(spotTarget ?? "");
    if (shown(target)) return target;
    if (target && $("more-menu").contains(target)) return $("more");
    return null;
  }

  function placeSpot() {
    const element = spotTarget ? spotElement() : null;
    if (!element) {
      ui.spot.hidden = true;
      return;
    }
    const box = element.getBoundingClientRect();
    const pad = 6;
    ui.spot.hidden = false;
    ui.spot.style.left = `${box.left - pad}px`;
    ui.spot.style.top = `${box.top - pad}px`;
    ui.spot.style.width = `${box.width + pad * 2}px`;
    ui.spot.style.height = `${box.height + pad * 2}px`;
  }

  function point(target) {
    spotTarget = target ?? null;
    placeSpot();
  }

  function menu(open) {
    if ($("more-menu").hidden === open) press("more");
  }

  // Watch: point at a control, let it be seen, then press it.
  async function pressShown(id, inMenu = false) {
    if (inMenu) menu(true);
    point(id);
    await wait(LEAD_MS);
    press(id);
  }

  // ---- The steps ----

  // The point half the route's length along it. A straight route has only its two ends.
  function halfway(path) {
    const lengths = path.slice(1).map((p, i) => Math.hypot(p[0] - path[i][0], p[2] - path[i][2]));
    let left = lengths.reduce((sum, length) => sum + length, 0) / 2;
    for (const [i, length] of lengths.entries()) {
      if (left <= length) {
        const along = left / length;
        return path[i].map((value, axis) => value + (path[i + 1][axis] - value) * along);
      }
      left -= length;
    }
    return path[path.length - 1];
  }

  // Try small movable things, nearest first, until one can go on the route's middle.
  async function blockTheRoute() {
    const path = view.route.state.route?.path;
    if (!path || path.length < 2) return false;
    const middle = halfway(path);
    const near = (object) => Math.hypot(object.center.x - middle[0], object.center.z - middle[2]);
    const small = (object) => {
      const { bbox_min: low, bbox_max: high } = object.asset;
      return Math.abs(high[0] - low[0]) < 1 && Math.abs(high[2] - low[2]) < 1;
    };
    const candidates = view.objects
      .filter((o) => o.asset.mobility === "movable" && !o.gone && small(o))
      .sort((a, b) => near(a) - near(b))
      .slice(0, 6);
    const before = JSON.stringify(path);
    for (const object of candidates) {
      const result = await view.moveObject(object, [middle[0], object.center.y, middle[2]]);
      if (result.ok) {
        moved = true;
        await until(() => JSON.stringify(view.route.state.route?.path) !== before, 4000);
        return true;
      }
    }
    return false;
  }

  // Wait for Val's answer: the messages have stopped changing for a moment.
  async function valAnswered() {
    let last = "";
    let still = 0;
    await until(() => {
      const now = $("val-messages").textContent;
      still = now === last ? still + POLL_MS : 0;
      last = now;
      return still > 1500;
    }, ANSWER_LIMIT_MS);
  }

  // How far the camera has gone, and turned, since a mark.
  function cameraMark() {
    const { position, quaternion } = view.camera;
    return { position: position.clone(), quaternion: quaternion.clone() };
  }
  function cameraChanged(mark) {
    const { position, quaternion } = view.camera;
    return position.distanceTo(mark.position) > 0.4 || quaternion.angleTo(mark.quaternion) > 0.35;
  }

  // Counts how many times something on or off has switched since the step began.
  function switches(read) {
    let last = read();
    let count = 0;
    return () => {
      const now = read();
      if (now !== last) {
        last = now;
        count++;
      }
      return count;
    };
  }

  const stage = () => view.views.state.stage;

  function buildSteps() {
    const fault = view.fault();
    const tag = fault ? view.nameOf(fault) : "the faulty device";
    const count = view.objects.filter((o) => !o.gone).length;
    const attention = view.objects.find(
      (o) => o !== fault && !o.gone && o.condition?.condition_state === "attention_required",
    );
    const someLinked = attention ?? view.objects.find((o) => o !== fault && !o.gone && o.asset.mapping);
    let mark = null;
    let switched = () => 0;
    let changesBefore = 0;
    let stagesSeen = new Set();

    const steps = [
      {
        title: "The real room",
        text: "This is Valmet's equipment room: a 3D scan shown live as Gaussian splats, on this machine, with no internet.",
        how: "Drag to look around. Walk with W A S D or the arrow keys, or the joystick on a touch screen.",
        task: "Look around, or take a few steps.",
        prepare: () => {
          press("reset");
          mark = cameraMark();
        },
        done: () => cameraChanged(mark),
        show: async () => {
          // A slow look to each side and back.
          const start = view.camera.rotation.y;
          for (const turn of [0.5, -0.5, 0]) {
            const from = view.camera.rotation.y;
            for (let i = 1; i <= 20 && state.running; i++) {
              view.camera.rotation.y = from + ((start + turn - from) * i) / 20;
              view.wake();
              await sleep(40);
            }
          }
        },
        hold: 1500,
      },
      {
        title: "Walk or fly",
        text: "Walk keeps you on the floor at eye height, and stops you at walls and machines. Fly goes anywhere, to see pipes overhead.",
        how: "Press F, or Actions, then Walk.",
        target: "mode",
        task: "Switch to Fly, then back to Walk.",
        prepare: () => (switched = switches(view.walking)),
        done: () => switched() >= 2,
        show: async () => {
          await pressShown("mode", true);
          await wait(1500);
          press("mode");
          menu(false);
        },
        hold: 1000,
      },
      {
        title: "From a simple model to the scan",
        text: "The same room in five views: darkness, a simple BIM with fitted shapes, a blob BIM from the scan's surfaces, the point cloud, and the real view.",
        how: "Press B for the next view, or Actions, then View.",
        target: "next-view",
        task: "Step through the views, back to the real view.",
        prepare: () => (stagesSeen = new Set([stage()])),
        done: () => {
          stagesSeen.add(stage());
          return stagesSeen.size >= 3 && stage() === "real";
        },
        show: async () => {
          menu(true);
          point("next-view");
          for (const name of view.views.available) {
            view.views.set(name);
            await wait(name === "dark" ? 1500 : 3000);
          }
          view.views.set("real");
          menu(false);
        },
        hold: 500,
      },
      {
        title: "Every object found",
        text: `${count} objects were extracted from the scan, each in a 3D frame. The frame colour shows the type. Range sets how far away frames are shown.`,
        how: "Actions, then Boxes and Range.",
        target: "boxes",
        task: "Turn the frames off and on again.",
        prepare: () => (switched = switches(view.boxesOn)),
        done: () => switched() >= 2,
        show: async () => {
          menu(true);
          point("range");
          handlers.set_boxes({ on: true });
          handlers.set_range({ metres: 10 });
          await wait(3000);
          menu(false);
        },
        hold: 4000,
      },
      someLinked && {
        title: "Tap an object",
        text: "Tap any frame to see its record: type, condition and health from Valmet's Excel pack, and how the record was linked, with how sure we are. Links are never invented: unlinked objects say so.",
        how: "Tap or click an object. Focus takes you to its best view.",
        target: () => (shown($("info")) ? $("info") : null),
        task: "Tap a framed object.",
        prepare: () => view.closeInfo(),
        done: () => Boolean(view.selected()),
        show: async () => {
          await view.goLookAt(someLinked);
        },
        hold: 6000,
        after: () => view.closeInfo(),
      },
      {
        title: "Equipment by importance",
        text: "The Objects list puts what needs attention first: condition, then urgency, criticality and health. Tap a row to go to it.",
        how: "Press L, or Objects.",
        target: "open-list",
        task: "Open the Objects list.",
        done: () => view.objectList.state.open,
        show: async () => {
          await pressShown("open-list");
          point("object-list");
        },
        hold: 5000,
        after: () => view.objectList.close(),
      },
      {
        title: "Filter what you see",
        text: "Filters narrow everything at once: frames, labels, the list and the map. By type, by condition, or by whether it can move.",
        how: "Press T, or Filters.",
        target: "open-filters",
        task: "Open Filters and pick a condition or a type.",
        done: () => Boolean(view.filters?.isActive()),
        show: async () => {
          await pressShown("open-filters");
          point("filter-panel");
          handlers.set_filter({ types: ["pump"], conditions: [], mobility: "any" });
          await wait(3500);
          handlers.set_filter({ types: [], conditions: ["attention_required"], mobility: "any" });
        },
        hold: 3500,
        after: () => {
          handlers.clear_filters();
          view.closeFilters();
        },
      },
      attention && {
        title: "Alerts as you walk",
        text: "Come within 4 metres of equipment in red or yellow condition and it glows, even through what's in front of it, with its tag, state and distance.",
        how: "Just walk. Filters, then Alerts nearby, chooses which ones show.",
        target: () => [...$("alert-badges").children].find(shown) ?? null,
        task: `Walk towards something in red or yellow, or press Show me.`,
        done: () => view.alertsActive(),
        show: async () => {
          await view.goLookAt(attention);
          view.closeInfo();
        },
        hold: 4500,
      },
      {
        title: "The map",
        text: "The map shows the walls, where you are and where you're looking, the route, and the equipment that has a record. Tap it to open the full map.",
        how: "Map.",
        target: "open-plan",
        task: "Open the map.",
        done: () => view.plan.state.open,
        show: async () => {
          await pressShown("open-plan");
        },
        hold: 3500,
      },
      fault && {
        title: `A route to ${tag}`,
        text: `One press plans a collision-free route to ${tag} for a person, 0.6 m wide, around walls, machines and anything moved.`,
        how: "Press G, or Go to the fault in the object's details.",
        target: "go-fault",
        task: "Press G to plan the route.",
        done: () => Boolean(view.route.state.route),
        show: async () => {
          if (!shown($("go-fault"))) handlers.go_to_fault();
          else await pressShown("go-fault");
          await until(() => view.route.state.route, 5000);
        },
        hold: 4000,
      },
      fault && {
        title: "Move something in the way",
        text: "Select a movable object and press Move: drag it, or nudge it with the arrow keys. R turns it, Page Up and Page Down raise and lower it. A move that would hit something is refused, and the route goes around the new spot.",
        how: "Tap an object, then Move, or M.",
        target: "move",
        task: "Move a cart or a chair onto the route.",
        prepare: () => (changesBefore = view.changeCount()),
        done: () => view.changeCount() > changesBefore,
        show: async () => {
          const done = await blockTheRoute();
          if (!done) ui.text.textContent = "Nothing could be moved there just now, so the route stays.";
        },
        hold: 4500,
      },
      fault && {
        title: "Walk there",
        text: "Walk the route. Nearby equipment shows its frame and details as you pass.",
        how: "Walk route.",
        target: "follow",
        task: "Press Walk route.",
        done: () => Boolean(view.route.state.walking),
        show: async () => {
          await pressShown("follow");
          await until(() => !view.route.state.walking, WALK_LIMIT_MS);
        },
        after: async () => {
          if (state.mode === "try") await until(() => !view.route.state.walking, WALK_LIMIT_MS);
          handlers.stop_walking();
        },
        hold: 1500,
      },
      {
        title: "Undo",
        text: "Every change is saved in a log, so it can be taken back one at a time, or all at once with Reset all. The scan itself is never changed.",
        how: "Ctrl+Z, or Actions, then Undo.",
        target: "undo-last",
        task: () =>
          view.changeCount() > changesAtStart
            ? "Undo the latest change."
            : "There's nothing of yours to undo just now, so press Next.",
        prepare: () => (changesBefore = view.changeCount()),
        done: () => view.changeCount() < changesBefore,
        show: async () => {
          // Only what was changed during the tutorial, never earlier work.
          if (view.changeCount() > changesAtStart) {
            await pressShown("undo-last", true);
            moved = false;
          } else point("undo-last");
          await wait(1500);
          menu(false);
        },
        hold: 2500,
      },
      {
        title: "Ask Val",
        text: `Val is the service assistant. It answers from the Excel records, cites them, and says how sure it is. ${fault ? `Reaching ${tag} starts the diagnosis by itself.` : ""}`,
        how: "Press V, or Ask Val. Type or use the microphone.",
        target: "open-copilot",
        task: `Ask Val something, such as "What's wrong with ${tag}?"`,
        prepare: () => (mark = $("val-messages").textContent),
        done: () => $("val-messages").textContent !== mark && $("val-messages").textContent.length > mark.length + 20,
        show: async () => {
          point("open-copilot");
          await wait(LEAD_MS);
          view.copilot.open(`What's wrong with ${tag}?`);
          await wait(800);
          await valAnswered();
        },
        hold: 7000,
      },
      {
        title: "Safe by design",
        text: "Val recommends checks for a person to do. It won't operate the plant or skip a safety step. It also takes commands, such as \"Show only tanks\".",
        how: 'Try "Turn off the pump", or "Show only tanks".',
        target: "copilot",
        task: 'Ask Val to "Turn off the pump", or press Show me.',
        prepare: () => (mark = $("val-messages").textContent),
        done: () => $("val-messages").textContent.length > mark.length + 20,
        show: async () => {
          view.copilot.open("Turn off the pump");
          await wait(800);
          await valAnswered();
          await wait(3000);
          view.copilot.open("Show only tanks");
          await wait(4000);
        },
        hold: 1500,
        after: () => {
          handlers.clear_filters();
          press("copilot-close");
        },
      },
      view.hasBim() && {
        title: "BIM and IFC",
        text: "A simulated BIM model, built from the scan: walls, floor, and each object as a fitted shape. Download IFC exports what's shown, or only the selected object, for BIM tools.",
        how: "Actions, then BIM.",
        target: "bim",
        task: "Open BIM, then close it.",
        prepare: () => (switched = switches(view.bimActive)),
        done: () => switched() >= 2,
        show: async () => {
          await pressShown("bim", true);
          point("bim-panel");
          await wait(5000);
          press("bim");
        },
        hold: 1000,
        after: () => {
          if (view.bimActive()) press("bim");
        },
      },
      {
        title: "That's the tour",
        text: "Everything is back as it was. Help lists every key and command.",
        how: "Press ?, or the ? button.",
        target: "open-help",
        hold: 4000,
      },
    ];
    return steps.filter(Boolean);
  }

  async function undoOurMove() {
    if (!moved) return;
    moved = false;
    await view.undoLast();
  }

  // Puts the viewer back, whichever step it was stopped on.
  async function tidy(before) {
    point(null);
    if (view.route.state.walking) handlers.stop_walking();
    await undoOurMove();
    if (view.bimActive()) press("bim");
    if (view.walking() !== before.walking) press("mode");
    view.views.set("real");
    handlers.clear_filters();
    view.closeFilters();
    view.objectList.close();
    view.closeInfo();
    menu(false);
    press("copilot-close");
    press("clear-route");
    handlers.set_boxes({ on: before.boxes });
    handlers.set_range({ metres: before.range });
    if (before.mapOpen) handlers.open_map();
    else handlers.close_map();
    press("reset");
  }

  // The first card: Watch, or Try it. Val and ?demo start Watch straight away.
  async function chooseMode() {
    ui.title.textContent = "Tutorial";
    ui.text.textContent =
      "A tour of what the viewer does, in about three minutes. Watch it play, or try each step yourself, with Show me if you get stuck.";
    ui.how.textContent = "";
    ui.count.textContent = "";
    ui.choice.hidden = false;
    for (const button of [ui.pause, ui.next, ui.show]) button.hidden = true;
    await until(() => state.mode !== null);
    ui.choice.hidden = true;
  }

  function showControls() {
    ui.pause.hidden = state.mode !== "watch";
    ui.next.hidden = false;
  }

  async function runStep(step) {
    if (state.mode === "watch") {
      ui.show.hidden = true;
      point(step.target);
      await step.prepare?.();
      await step.show?.();
      point(step.target);
      if (step.hold) await wait(step.hold);
    } else {
      point(step.target);
      await step.prepare?.();
      showMe = false;
      ui.show.hidden = !step.show;
      const task = typeof step.task === "function" ? step.task() : step.task;
      if (task) ui.how.textContent = `Your turn: ${task} ${step.how ?? ""}`;
      // Without a task, Next moves on.
      if (step.done || step.task) await until(() => showMe || Boolean(step.done?.()));
      ui.show.hidden = true;
      if (!state.running) return;
      if (showMe) {
        await step.show?.();
        point(step.target);
        if (step.hold) await wait(step.hold);
      } else if (step.done?.()) {
        ui.how.textContent = "Done. On to the next one.";
        await wait(PRAISE_MS);
      }
    }
    await step.after?.();
  }

  async function start(mode = null) {
    if (state.running) return { ok: false, message: "The tutorial is already running." };
    state.running = true;
    state.paused = false;
    state.mode = mode;
    ui.pause.textContent = "Pause";
    ui.panel.hidden = false;
    clearInterval(spotTimer);
    spotTimer = setInterval(placeSpot, 150); // controls move as panels open and close
    changesAtStart = view.changeCount();
    const before = {
      range: view.range(),
      mapOpen: view.plan.state.open,
      boxes: view.boxesOn(),
      walking: view.walking(),
    };
    if (!state.mode) await chooseMode();
    if (state.running) {
      showControls();
      const steps = buildSteps();
      for (const [index, step] of steps.entries()) {
        if (!state.running) break;
        ui.title.textContent = step.title;
        ui.text.textContent = step.text;
        ui.how.textContent = step.how ?? "";
        ui.count.textContent = `${index + 1} of ${steps.length}`;
        try {
          await runStep(step);
        } catch (error) {
          // One step going wrong shouldn't end the tutorial.
          console.warn(`Tutorial step "${step.title}": ${error.message}`);
        }
      }
    }
    state.running = false;
    ui.panel.hidden = true;
    ui.choice.hidden = true;
    clearInterval(spotTimer);
    try {
      await tidy(before);
    } catch (error) {
      console.warn(`Tutorial tidying: ${error.message}`);
    }
    state.mode = null;
    return { ok: true, message: "" };
  }

  function stop() {
    state.running = false;
    skip++;
  }

  ui.next.onclick = () => skip++;
  ui.stop.onclick = stop;
  ui.show.onclick = () => (showMe = true);
  ui.watch.onclick = () => (state.mode = "watch");
  ui.tryIt.onclick = () => (state.mode = "try");
  ui.pause.onclick = () => {
    state.paused = !state.paused;
    ui.pause.textContent = state.paused ? "Resume" : "Pause";
  };

  return { state, start, stop };
}
