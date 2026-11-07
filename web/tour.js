// The demo: a guided run through the viewer, one step at a time, using the same commands as the
// buttons and Val. Anything it changes it puts back at the end, even if it's stopped halfway.

const POLL_MS = 100;
const WALK_LIMIT_MS = 60000;
const ANSWER_LIMIT_MS = 12000;

export function setupTour({ ui, handlers, press, view }) {
  const state = { running: false, paused: false };
  let skip = 0; // each press of Next ends what's being waited for
  let moved = false; // whether there's a move of ours to undo

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function wait(ms) {
    const token = skip;
    let left = ms;
    while (left > 0 && token === skip && state.running) {
      await sleep(POLL_MS);
      if (!state.paused) left -= POLL_MS;
    }
  }

  async function until(done, limit) {
    const token = skip;
    let left = limit;
    while (left > 0 && token === skip && state.running && !done()) {
      await sleep(POLL_MS);
      if (!state.paused) left -= POLL_MS;
    }
  }

  // Wait for Val's answer: the messages have stopped changing for a moment.
  async function valAnswered() {
    let last = "";
    let still = 0;
    await until(() => {
      const now = document.getElementById("val-messages").textContent;
      still = now === last ? still + POLL_MS : 0;
      last = now;
      return still > 1500;
    }, ANSWER_LIMIT_MS);
  }

  // The point half the route's length along it. A straight route has only its two ends.
  function halfway(path) {
    const lengths = path.slice(1).map((point, i) => Math.hypot(point[0] - path[i][0], point[2] - path[i][2]));
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

  function buildSteps() {
    const fault = view.fault();
    const tag = fault ? view.nameOf(fault) : "";
    const count = view.objects.filter((o) => !o.gone).length;
    const steps = [
      {
        title: "A real room",
        text: "This is the equipment room, scanned and shown as a live 3D scene. It runs on our own server, with no internet.",
        run: async () => press("reset"),
        hold: 6000,
      },
      {
        title: "Every object found",
        text: `${count} objects were extracted from the scan, each with a 3D frame. The colour shows the type.`,
        run: async () => {
          handlers.set_boxes({ on: true });
          handlers.set_range({ metres: 10 });
        },
        hold: 7000,
      },
      {
        title: "Filter what you see",
        text: "Filters narrow everything at once: frames, labels, the list and the map. First the pumps, then only what needs attention.",
        run: async () => {
          view.openFilters();
          handlers.set_filter({ types: ["pump"], conditions: [], mobility: "any" });
          await wait(4500);
          handlers.set_filter({ types: [], conditions: ["attention_required"], mobility: "any" });
          await wait(4500);
          handlers.clear_filters();
          view.closeFilters();
        },
      },
      {
        title: "Equipment by importance",
        text: "The list puts what needs attention first. Tap one to go to its best view and see its record, with how it was linked and how sure we are.",
        run: async () => {
          view.objectList.open();
          await wait(3000);
          const first = view.objects.find(
            (o) => o !== fault && !o.gone && o.condition === "attention_required",
          );
          if (first) await view.goLookAt(first);
          await wait(5000);
          view.objectList.close();
          view.closeInfo();
          press("reset");
        },
      },
    ];
    if (fault) {
      steps.push(
        {
          title: "A route to the fault",
          text: `A collision-free route to ${tag}, on the minimap too: where you are, where you're going, and the walls and fixed equipment.`,
          run: async () => {
            handlers.open_map();
            handlers.go_to_fault();
            await until(() => view.route.state.route, 5000);
          },
          hold: 6000,
        },
        {
          title: "Move something in the way",
          text: "Objects can be moved. Put one on the route, and the route goes around it. A move that would hit something is refused.",
          run: async () => {
            const done = await blockTheRoute();
            if (!done) ui.text.textContent = "Nothing could be moved there just now, so the route stays.";
          },
          hold: 6000,
        },
        {
          title: "Walk there",
          text: "Walking the route, nearby equipment shows its frame and details as you pass.",
          run: async () => {
            handlers.walk_route();
            await until(() => !view.route.state.walking, WALK_LIMIT_MS);
            handlers.stop_walking();
            await undoOurMove();
          },
          hold: 1500,
        },
        {
          title: "Ask Val on arrival",
          text: `Val answers from the Excel records and cites them. It keeps what's recorded apart from what it infers, and says how sure it is.`,
          run: async () => {
            view.copilot.open(`Why is ${tag} at attention required?`);
            await wait(800);
            await valAnswered();
          },
          hold: 9000,
        },
        {
          title: "Val keeps to the safety rules",
          text: "Val won't tell you how to bypass a safety step, or operate the plant. A person has to do that, by the procedure.",
          run: async () => {
            view.copilot.open("Turn off the pump");
            await wait(800);
            await valAnswered();
          },
          hold: 5000,
        },
      );
    }
    steps.push({
      title: "Talk to it",
      text: "The viewer also takes commands, typed or by voice with the microphone, on this machine. Here: show only the tanks.",
      run: async () => {
        view.copilot.open("Show only tanks");
        await wait(5000);
        handlers.clear_filters();
        press("copilot-close");
      },
    });
    if (view.bim()) {
      steps.push({
        title: "A BIM model from the scan",
        text: "The same objects as a simple BIM model, with their properties and an IFC file to download. It's simulated from the scan, not surveyed.",
        run: async () => {
          handlers.set_bim({ on: true });
        },
        hold: 8000,
        after: async () => handlers.set_bim({ on: false }),
      });
    }
    steps.push({
      title: "That's the tour",
      text: "Everything is back as it was. Open Filters, Objects, the Map or Val to carry on from here.",
      run: async () => press("reset"),
      hold: 4000,
    });
    return steps;
  }

  async function undoOurMove() {
    if (!moved) return;
    moved = false;
    await view.undoLast();
  }

  // Puts the viewer back, whichever step it was stopped on.
  async function tidy(before) {
    if (view.route.state.walking) handlers.stop_walking();
    await undoOurMove();
    if (view.bim()?.state.active) handlers.set_bim({ on: false });
    handlers.clear_filters();
    view.closeFilters();
    view.objectList.close();
    view.closeInfo();
    press("copilot-close");
    press("clear-route");
    handlers.set_range({ metres: before.range });
    if (before.mapOpen) handlers.open_map();
    else handlers.close_map();
    press("reset");
  }

  async function start() {
    if (state.running) return { ok: false, message: "The demo is already running." };
    state.running = true;
    state.paused = false;
    ui.pause.textContent = "Pause";
    ui.panel.hidden = false;
    const before = { range: view.range(), mapOpen: view.plan.state.open };
    const steps = buildSteps();
    for (const [index, step] of steps.entries()) {
      if (!state.running) break;
      ui.title.textContent = step.title;
      ui.text.textContent = step.text;
      ui.count.textContent = `${index + 1} of ${steps.length}`;
      try {
        await step.run();
        if (step.hold) await wait(step.hold);
        await step.after?.();
      } catch (error) {
        // One step going wrong shouldn't end the demo.
        console.warn(`Demo step "${step.title}": ${error.message}`);
      }
    }
    state.running = false;
    ui.panel.hidden = true;
    try {
      await tidy(before);
    } catch (error) {
      console.warn(`Demo tidying: ${error.message}`);
    }
    return { ok: true, message: "" };
  }

  function stop() {
    state.running = false;
    skip++;
  }

  ui.next.onclick = () => skip++;
  ui.stop.onclick = stop;
  ui.pause.onclick = () => {
    state.paused = !state.paused;
    ui.pause.textContent = state.paused ? "Resume" : "Pause";
  };

  return { state, start, stop };
}
