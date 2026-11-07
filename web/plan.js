// Plan: a 2D blueprint of the room from above, with the walls, the equipment, the route, and where
// you are. Generated from the scan, not surveyed, and it says so on screen.
//
// It's light on purpose. Walls and the room outline come from the BIM model (bim.json, built
// offline), the walkable floor from /api/plan/walkable, and equipment from the objects as they stand
// now. Nothing heavy is computed to open it, and it redraws at most about ten times a second.

const PADDING = 16;
const LABEL_HEIGHT = 16;
const MARGIN_M = 0.5; // metres of paper around the room
const FRAME_MS = 100;

// Blueprint colours: paper, a faint 1 m grid, white lines.
const PAPER = "#123a63";
const GRID = "rgba(255, 255, 255, 0.07)";
const WALKABLE = [0x1d, 0x52, 0x86]; // a lighter blue where a person can walk
const WALL = "#f1f5f9";
const LINE = "#cfe3f7";
const LINKED = "#ffffff";
const FAULT_COLOR = "#ff6b4a";
const FOUND_COLOR = "#facc15";
const ROUTE_COLOR = "#38bdf8";
const FAINT = "rgba(207, 227, 247, 0.45)";
const LEGEND = [
  ["Faulty device", FAULT_COLOR],
  ["Linked to a record", LINKED],
  ["Other equipment", FAINT],
  ["Walkable floor", `rgb(${WALKABLE.join(",")})`],
  ["Route", ROUTE_COLOR],
];
const HIDDEN_UNLESS_ASKED = new Set(["pipe", "pipe fitting", "cable", "hose", "light fixture"]);

export function setupPlan({
  ui,
  objects,
  root,
  camera,
  route,
  getFaultTag,
  getSelected,
  nameOf,
  onSelect,
}) {
  const context = ui.canvas.getContext("2d");
  const floor = document.createElement("canvas"); // the walkable mask, one pixel per cell
  const state = {
    open: false,
    ready: false,
    description: null, // { x_min, x_max, z_min, z_max, walls: [{ x0, x1, z0, z1 }] }
    floor: null, // { x0, z0, x1, z1 } of the walkable mask, once loaded
    showPipes: false,
    found: new Set(),
    lastDraw: 0,
  };

  function fit() {
    const box = ui.canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.round(box.width * ratio);
    const height = Math.round(box.height * ratio);
    // Setting a canvas's size clears it, so only do that when the size has changed.
    if (ui.canvas.width !== width || ui.canvas.height !== height) {
      ui.canvas.width = width;
      ui.canvas.height = height;
    }
    const d = state.description;
    const scale = Math.min(
      (box.width - 2 * PADDING) / (d.x_max - d.x_min),
      (box.height - 2 * PADDING) / (d.z_max - d.z_min),
    );
    const left = (box.width - scale * (d.x_max - d.x_min)) / 2;
    const top = (box.height - scale * (d.z_max - d.z_min)) / 2;
    return { scale, left, top, ratio, width: box.width, height: box.height };
  }

  // +z points up the page, the way the scan's start view faces.
  function toScreen(view, x, z) {
    const d = state.description;
    return [view.left + (x - d.x_min) * view.scale, view.top + (d.z_max - z) * view.scale];
  }

  function isHighlighted(object) {
    return object === getSelected() || state.found.has(object);
  }

  function shown(object) {
    if (object.gone) return false;
    if (isHighlighted(object) || object.asset.mapping) return true;
    return state.showPipes || !HIDDEN_UNLESS_ASKED.has(object.asset.label);
  }

  // An object's footprint on screen. Its size comes from its box, its place from where it is now.
  function footprint(view, object) {
    const a = object.asset;
    const halfX = Math.abs(a.bbox_max[0] - a.bbox_min[0]) / 2;
    const halfZ = Math.abs(a.bbox_max[2] - a.bbox_min[2]) / 2;
    const [left, top] = toScreen(view, object.center.x - halfX, object.center.z + halfZ);
    return { left, top, width: 2 * halfX * view.scale, height: 2 * halfZ * view.scale };
  }

  // Important names go first. A name with no free spot waits until its object is found or tapped.
  function drawLabels(c, view, labels) {
    c.font = "12px system-ui, sans-serif";
    c.textAlign = "left";
    const placed = [];
    labels.sort((a, b) => b.rank - a.rank);
    for (const { text, box, color, rank } of labels) {
      const width = c.measureText(text).width + 8;
      const middleY = box.top + box.height / 2 - LABEL_HEIGHT / 2;
      const middleX = box.left + box.width / 2 - width / 2;
      const spots = [
        [middleX, box.top - LABEL_HEIGHT - 2],
        [middleX, box.top + box.height + 2],
        [box.left - width - 2, middleY],
        [box.left + box.width + 2, middleY],
      ].map(([x, y]) => [
        Math.max(2, Math.min(x, view.width - width - 2)),
        Math.max(2, Math.min(y, view.height - LABEL_HEIGHT - 2)),
      ]);
      const free = spots.find(([x, y]) =>
        placed.every(
          (other) =>
            x + width < other.x ||
            other.x + other.width < x ||
            y + LABEL_HEIGHT < other.y ||
            other.y + LABEL_HEIGHT < y,
        ),
      );
      const spot = free ?? (rank > 1 ? spots[0] : null);
      if (!spot) continue;
      placed.push({ x: spot[0], y: spot[1], width });
      c.fillStyle = "rgba(18, 58, 99, 0.92)";
      c.fillRect(spot[0], spot[1], width, LABEL_HEIGHT);
      c.fillStyle = color;
      c.fillText(text, spot[0] + 4, spot[1] + 12);
    }
  }

  function drawGrid(c, view) {
    const d = state.description;
    c.strokeStyle = GRID;
    c.lineWidth = 1;
    c.beginPath();
    for (let x = Math.ceil(d.x_min); x <= d.x_max; x++) {
      const [sx] = toScreen(view, x, d.z_max);
      c.moveTo(sx, view.top);
      c.lineTo(sx, view.top + (d.z_max - d.z_min) * view.scale);
    }
    for (let z = Math.ceil(d.z_min); z <= d.z_max; z++) {
      const [, sy] = toScreen(view, d.x_min, z);
      c.moveTo(view.left, sy);
      c.lineTo(view.left + (d.x_max - d.x_min) * view.scale, sy);
    }
    c.stroke();
  }

  function drawFloor(c, view) {
    const f = state.floor;
    if (!f) return;
    const [x, y] = toScreen(view, f.x0, f.z1);
    c.imageSmoothingEnabled = true;
    c.drawImage(floor, x, y, (f.x1 - f.x0) * view.scale, (f.z1 - f.z0) * view.scale);
  }

  function drawWalls(c, view) {
    c.fillStyle = WALL;
    for (const wall of state.description.walls) {
      const [left, top] = toScreen(view, wall.x0, wall.z1);
      c.fillRect(
        left,
        top,
        Math.max((wall.x1 - wall.x0) * view.scale, 3),
        Math.max((wall.z1 - wall.z0) * view.scale, 3),
      );
    }
  }

  function drawRoute(c, view) {
    const path = route.state.route?.path;
    if (!path?.length) return;
    c.beginPath();
    c.strokeStyle = ROUTE_COLOR;
    c.lineWidth = 3;
    c.setLineDash([8, 5]);
    path.forEach((point, index) => {
      const [x, y] = toScreen(view, point[0], point[2]);
      if (index) c.lineTo(x, y);
      else c.moveTo(x, y);
    });
    c.stroke();
    c.setLineDash([]);
  }

  // Where you are, and which way you face: a dot with a wedge, as on a paper plan.
  function drawViewer(c, view) {
    const here = root.worldToLocal(camera.position.clone());
    const ahead = root.worldToLocal(
      camera.position.clone().add(camera.getWorldDirection(here.clone())),
    );
    const [x, y] = toScreen(view, here.x, here.z);
    const [aheadX, aheadY] = toScreen(view, ahead.x, ahead.z);
    const facing = Math.atan2(aheadY - y, aheadX - x);
    c.beginPath();
    c.moveTo(x, y);
    c.arc(x, y, 30, facing - 0.45, facing + 0.45);
    c.closePath();
    c.fillStyle = "rgba(56, 189, 248, 0.3)";
    c.fill();
    c.beginPath();
    c.arc(x, y, 6, 0, 2 * Math.PI);
    c.fillStyle = ROUTE_COLOR;
    c.fill();
    c.lineWidth = 2;
    c.strokeStyle = "#ffffff";
    c.stroke();
  }

  // One metre, in the scan's own units, which haven't been checked on site.
  function drawScale(c, view) {
    const d = state.description;
    const x = view.left + 14;
    const y = view.top + (d.z_max - d.z_min) * view.scale - 12;
    c.strokeStyle = WALL;
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(x, y - 5);
    c.lineTo(x, y);
    c.lineTo(x + view.scale, y);
    c.lineTo(x + view.scale, y - 5);
    c.stroke();
    c.font = "12px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillStyle = WALL;
    c.fillText("1 m, scan's scale", x, y - 8);
  }

  function draw(now = performance.now()) {
    if (!state.open || !state.ready) return;
    if (now - state.lastDraw < FRAME_MS) return;
    state.lastDraw = now;
    const view = fit();
    const c = context;
    c.setTransform(view.ratio, 0, 0, view.ratio, 0, 0);
    c.fillStyle = PAPER;
    c.fillRect(0, 0, view.width, view.height);
    drawGrid(c, view);
    drawFloor(c, view);
    drawWalls(c, view);

    const labels = [];
    for (const object of objects) {
      if (!shown(object)) continue;
      const box = footprint(view, object);
      const fault = object.asset.mapping?.tag === getFaultTag();
      const highlighted = isHighlighted(object);
      const color = fault ? FAULT_COLOR : object.asset.mapping ? LINKED : FAINT;
      if (fault || highlighted) {
        c.fillStyle = `${fault ? FAULT_COLOR : FOUND_COLOR}33`;
        c.fillRect(box.left, box.top, box.width, box.height);
      }
      c.strokeStyle = highlighted ? FOUND_COLOR : color;
      c.lineWidth = highlighted || fault ? 2.5 : object.asset.mapping ? 1.5 : 1;
      c.setLineDash(object.asset.mobility === "movable" ? [4, 3] : []);
      c.strokeRect(box.left, box.top, box.width, box.height);
      if (object.asset.mapping || highlighted) {
        const rank = highlighted ? 3 : fault ? 2 : 1;
        labels.push({ text: nameOf(object), box, color: highlighted ? FOUND_COLOR : color, rank });
      }
    }
    c.setLineDash([]);

    drawRoute(c, view);
    drawLabels(c, view, labels);
    drawViewer(c, view);
    drawScale(c, view);
  }

  function objectAt(view, x, y) {
    const near = 6; // pixels of tolerance, for small objects under a finger
    let best = null;
    let bestArea = Infinity;
    for (const object of objects) {
      if (!shown(object)) continue;
      const box = footprint(view, object);
      const inside =
        x >= box.left - near &&
        x <= box.left + box.width + near &&
        y >= box.top - near &&
        y <= box.top + box.height + near;
      if (inside && box.width * box.height < bestArea) {
        best = object;
        bestArea = box.width * box.height;
      }
    }
    return best;
  }

  ui.canvas.addEventListener("click", (event) => {
    if (!state.ready) return;
    const box = ui.canvas.getBoundingClientRect();
    const found = objectAt(fit(), event.clientX - box.left, event.clientY - box.top);
    if (found) onSelect(found);
  });

  function search(text) {
    const wanted = text.trim().toLowerCase();
    state.found.clear();
    state.lastDraw = 0;
    ui.note.textContent = "";
    if (!wanted) return;
    const here = objects.filter((object) => !object.gone);
    const byTag = here.filter(
      (object) =>
        (object.asset.mapping?.tag ?? "").toLowerCase().includes(wanted) ||
        object.asset.object_id.toLowerCase() === wanted,
    );
    const byType = here.filter((object) => object.asset.label?.toLowerCase() === wanted);
    const matches = byTag.length ? byTag : byType;
    for (const object of matches) state.found.add(object);
    if (!matches.length) ui.note.textContent = "Nothing with that tag or type.";
    else if (matches.length === 1) ui.note.textContent = `Found ${nameOf(matches[0])}.`;
    else ui.note.textContent = `Found ${matches.length}.`;
  }
  ui.search.addEventListener("input", () => search(ui.search.value));

  ui.pipes.onclick = () => {
    state.showPipes = !state.showPipes;
    state.lastDraw = 0;
    ui.pipes.textContent = state.showPipes ? "Hide pipes" : "Show pipes";
  };

  for (const [text, color] of LEGEND) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.background = color;
    item.append(swatch, text);
    ui.legend.append(item);
  }
  const dashed = document.createElement("span");
  const sample = document.createElement("i");
  sample.className = "dashed";
  dashed.append(sample, "Dashed: can move");
  ui.legend.append(dashed);

  // The room and walls from the BIM model, built offline. Without it, the room is framed on the
  // objects, with no walls drawn.
  async function loadRoom() {
    const model = await fetch("bim.json")
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
    const faces = model?.room?.faces;
    const walls = (model?.elements ?? [])
      .filter((element) => element.ifc_class === "IfcWall" && element.geometry?.type === "box")
      .map(({ geometry: { center, size } }) => ({
        x0: center[0] - size[0] / 2,
        x1: center[0] + size[0] / 2,
        z0: center[2] - size[2] / 2,
        z1: center[2] + size[2] / 2,
      }));
    let bounds;
    if (faces) {
      bounds = [faces.first_min, faces.first_max, faces.second_min, faces.second_max];
    } else {
      const xs = objects.map((o) => o.center.x);
      const zs = objects.map((o) => o.center.z);
      bounds = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
    }
    for (const wall of walls) {
      bounds = [
        Math.min(bounds[0], wall.x0),
        Math.max(bounds[1], wall.x1),
        Math.min(bounds[2], wall.z0),
        Math.max(bounds[3], wall.z1),
      ];
    }
    state.description = {
      x_min: bounds[0] - MARGIN_M,
      x_max: bounds[1] + MARGIN_M,
      z_min: bounds[2] - MARGIN_M,
      z_max: bounds[3] + MARGIN_M,
      walls,
    };
  }

  // Where a person can walk now, as lighter paper. Optional: the plan works without it.
  async function loadFloor() {
    const reply = await fetch("/api/plan/walkable")
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
    if (!reply || reply.axes?.[0] !== 0 || reply.axes?.[1] !== 2) return;
    const [rows, cols] = reply.shape; // rows run along x, columns along z
    const bits = Uint8Array.from(atob(reply.mask), (ch) => ch.charCodeAt(0));
    floor.width = rows;
    floor.height = cols;
    const c = floor.getContext("2d");
    const pixels = c.createImageData(rows, cols);
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const index = i * cols + j;
        if (!((bits[index >> 3] >> (7 - (index & 7))) & 1)) continue;
        const p = ((cols - 1 - j) * rows + i) * 4; // +z up the page
        pixels.data.set([...WALKABLE, 255], p);
      }
    }
    c.putImageData(pixels, 0, 0);
    const [x0, z0] = reply.origin;
    state.floor = { x0, z0, x1: x0 + rows * reply.cell, z1: z0 + cols * reply.cell };
  }

  async function open() {
    state.open = true;
    state.lastDraw = 0;
    ui.panel.hidden = false;
    loadFloor().then(() => (state.lastDraw = 0)); // moved objects change it, so refresh each time
    if (state.ready) return;
    ui.note.textContent = "Drawing the plan...";
    await loadRoom();
    state.ready = true;
    ui.dxf.hidden = false;
    ui.note.textContent = state.description.walls.length
      ? ""
      : "No BIM model, so no walls: run make bim.";
  }

  function close() {
    state.open = false;
    ui.panel.hidden = true;
  }

  return { state, open, close, draw, search };
}
