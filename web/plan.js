// Bird's-eye floor layout: the room from above, with objects, the route, and where you are.
// Generated from the scan, not surveyed, and it says so on screen.

const PADDING = 16;
const LABEL_HEIGHT = 16;
const FAULT_COLOR = "#ff2d2d";
const LINKED_COLOR = "#ffffff";
const FOUND_COLOR = "#facc15";
const ROUTE_COLOR = "#22d3ee";
const OTHER_COLOR = "#9ca3af";
// The same colours as BIM mode, so a type looks the same in both.
const TYPE_COLORS = {
  tank: "#22c55e",
  pump: "#f59e0b",
  valve: "#a855f7",
  pipe: "#3b82f6",
  hose: "#3b82f6",
  "pipe fitting": "#93c5fd",
  cable: "#eab308",
  "electrical cabinet": "#14b8a6",
  "light fixture": "#fde68a",
  sensor: "#ec4899",
  gauge: "#ec4899",
  chair: "#b45309",
  shelf: "#b45309",
};
const LEGEND = [
  ["Faulty device", FAULT_COLOR],
  ["Linked to a record", LINKED_COLOR],
  ["Tank", TYPE_COLORS.tank],
  ["Pump", TYPE_COLORS.pump],
  ["Valve", TYPE_COLORS.valve],
  ["Cabinet", TYPE_COLORS["electrical cabinet"]],
  ["Furniture", TYPE_COLORS.chair],
  ["Other", OTHER_COLOR],
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
  const image = new Image();
  const state = { open: false, ready: false, description: null, showPipes: false, found: new Set() };

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

  function colorOf(object) {
    if (object.asset.mapping?.tag === getFaultTag()) return FAULT_COLOR;
    if (object.asset.mapping) return LINKED_COLOR;
    return TYPE_COLORS[object.asset.label] ?? OTHER_COLOR;
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
      c.fillStyle = "rgba(15, 20, 25, 0.9)";
      c.fillRect(spot[0], spot[1], width, LABEL_HEIGHT);
      c.fillStyle = color;
      c.fillText(text, spot[0] + 4, spot[1] + 12);
    }
  }

  function drawRoute(c, view) {
    const path = route.state.route?.path;
    if (!path?.length) return;
    c.beginPath();
    c.strokeStyle = ROUTE_COLOR;
    c.lineWidth = 4;
    path.forEach((point, index) => {
      const [x, y] = toScreen(view, point[0], point[2]);
      if (index) c.lineTo(x, y);
      else c.moveTo(x, y);
    });
    c.stroke();
  }

  // Where you are, and which way you face.
  function drawViewer(c, view) {
    const here = root.worldToLocal(camera.position.clone());
    const ahead = root.worldToLocal(
      camera.position.clone().add(camera.getWorldDirection(here.clone())),
    );
    const [x, y] = toScreen(view, here.x, here.z);
    const [aheadX, aheadY] = toScreen(view, ahead.x, ahead.z);
    c.save();
    c.translate(x, y);
    c.rotate(Math.atan2(aheadY - y, aheadX - x));
    c.beginPath();
    c.moveTo(14, 0);
    c.lineTo(-8, -8);
    c.lineTo(-4, 0);
    c.lineTo(-8, 8);
    c.closePath();
    c.fillStyle = ROUTE_COLOR;
    c.strokeStyle = "#0f1419";
    c.lineWidth = 2;
    c.fill();
    c.stroke();
    c.restore();
  }

  // One metre, in the scan's own units, which haven't been checked on site.
  function drawScale(c, view) {
    const d = state.description;
    const x = view.left + 14;
    const y = view.top + (d.z_max - d.z_min) * view.scale - 12;
    c.font = "12px system-ui, sans-serif";
    c.textAlign = "left";
    c.fillStyle = "rgba(15, 20, 25, 0.9)";
    c.fillRect(x - 8, y - 24, Math.max(view.scale + 16, 120), 32);
    c.strokeStyle = "#f8fafc";
    c.lineWidth = 3;
    c.beginPath();
    c.moveTo(x, y);
    c.lineTo(x + view.scale, y);
    c.stroke();
    c.fillStyle = "#f8fafc";
    c.fillText("1 m, scan's scale", x, y - 8);
  }

  function draw() {
    if (!state.open || !state.ready) return;
    const view = fit();
    const c = context;
    const d = state.description;
    c.setTransform(view.ratio, 0, 0, view.ratio, 0, 0);
    c.clearRect(0, 0, view.width, view.height);
    c.drawImage(
      image,
      view.left,
      view.top,
      (d.x_max - d.x_min) * view.scale,
      (d.z_max - d.z_min) * view.scale,
    );

    c.strokeStyle = "#f8fafc";
    c.lineWidth = 3;
    for (const wall of d.walls) {
      c.beginPath();
      c.moveTo(...toScreen(view, ...wall.start));
      c.lineTo(...toScreen(view, ...wall.end));
      c.stroke();
    }

    const labels = [];
    for (const object of objects) {
      if (!shown(object)) continue;
      const box = footprint(view, object);
      const color = colorOf(object);
      const highlighted = isHighlighted(object);
      c.fillStyle = `${color}33`;
      c.fillRect(box.left, box.top, box.width, box.height);
      c.strokeStyle = highlighted ? FOUND_COLOR : color;
      c.lineWidth = highlighted || color === FAULT_COLOR ? 3 : 1.5;
      c.setLineDash(object.asset.mobility === "movable" ? [5, 4] : []);
      c.strokeRect(box.left, box.top, box.width, box.height);
      if (object.asset.mapping || highlighted) {
        const rank = highlighted ? 3 : color === FAULT_COLOR ? 2 : 1;
        labels.push({ text: nameOf(object), box, color, rank });
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

  async function open() {
    state.open = true;
    ui.panel.hidden = false;
    if (state.ready) return;
    ui.note.textContent = "Building the layout...";
    try {
      const response = await fetch("/api/plan");
      const reply = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(reply.detail ?? `backend error ${response.status}`);
      state.description = reply;
      image.src = "/api/plan/floor.png";
      await image.decode();
      state.ready = true;
      ui.dxf.hidden = false;
      ui.note.textContent = "";
    } catch (error) {
      ui.note.textContent = `Couldn't build the layout: ${error.message}.`;
    }
  }

  function close() {
    state.open = false;
    ui.panel.hidden = true;
  }

  return { state, open, close, draw, search };
}
