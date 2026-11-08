// Plant room viewer: walk through the splat scene like a camera feed, with object boxes and labels.
// Data: /scene.ply (Gaussian splat) and /assets.json (same format as fixtures/sample_assets.json),
// both served by web/serve.py.
import * as THREE from "three";
import { SparkControls, SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { setupAddObject } from "./addobject.js";
import { setupBim } from "./bim.js";
import { setupCommands } from "./commands.js";
import { FAULT_COLOR, LEGEND, colorForLabel } from "./colors.js";
import { setupCopilot } from "./copilot.js";
import { setupHighlight } from "./highlight.js";
import { createHoverShell } from "./hover.js";
import { THIN_LABELS, pickFront } from "./pick.js";
import { setupObjects } from "./objects.js";
import { setupPacing } from "./pacing.js";
import { setupPhone } from "./phone.js";
import { setupAlerts } from "./alerts.js";
import { setupObjectList } from "./objectlist.js";
import { setupFilters } from "./filters.js";
import { setupPlan } from "./plan.js";
import { setupWalkable } from "./walkable.js";
import { setupWalkXR, xrSupported } from "./xr.js";
import { setupRoute } from "./route.js";
import { setupTour } from "./tour.js";
import { setupViews } from "./views.js";

let faultTag = "P-005"; // the pre-chosen faulty device, unless the scene's file names another
const EYE_HEIGHT = 1.6; // metres above the floor in walk mode (scene units look close to metres)
const RANGES = [2, 3, 5, 10]; // metres the Range button cycles through, for frames and labels
const MAX_BOXES = 15;
const BACKGROUND_LABELS = new Set(["pipe", "pipe fitting", "cable", "hose", "object"]);
// Rough size of a label on screen, to keep them from overlapping.
const LABEL_CHAR_PX = 6.5;
const LABEL_PAD_PX = 14;
const LABEL_HEIGHT_PX = 22;

// Lighter defaults for tablets, until they're measured on the real Lenovo.
const TABLET_RES = 0.75;
const TABLET_SPLATS = 500000;

// Speed settings, changeable in the URL without editing code, e.g. ?res=0.5&splats=300000
//   res     render resolution relative to the screen (default 1; 0.5 is about 4x fewer pixels)
//   lod     1 = level of detail on: far-away areas use fewer, bigger splats (default 1)
//   splats  how many splats LOD aims to draw per frame (default: Spark's choice for the device)
//   adaptive  1 lowers the resolution while moving, for slow devices (default 0: it flickers)
//   debug   1 shows the frame rate and object counts
const params = new URLSearchParams(location.search);
const DEBUG = params.has("debug");
document.body.classList.toggle("debug", DEBUG);
//   tablet  1 or 0 forces the touch layout and lighter defaults. Default: on for touch screens
const TABLET = params.has("tablet")
  ? params.get("tablet") === "1"
  : window.matchMedia("(pointer: coarse)").matches;
document.body.classList.toggle("tablet", TABLET);
const MAX_LABELS = TABLET ? 5 : 8;
const RES = Number(params.get("res") ?? (TABLET ? TABLET_RES : 1));
const LOD = params.get("lod") !== "0";
// Off by default: changing the resolution resizes the canvas, which flickers on every start and
// stop. Turn it on for a device that can't keep up.
const ADAPTIVE = params.get("adaptive") === "1";
const LOD_SPLATS = params.has("splats")
  ? Number(params.get("splats"))
  : TABLET
    ? TABLET_SPLATS
    : undefined;
// A separate graphics card can draw the full scene. Anything else draws much faster with the light
// scene (every splat, base colour only, about 4x smaller), if the server offers one.
function hasGraphicsCard() {
  const gl = document.createElement("canvas").getContext("webgl2");
  const info = gl?.getExtension("WEBGL_debug_renderer_info");
  const name = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "";
  return /nvidia|geforce|quadro|rtx|radeon rx|radeon pro|arc\b/i.test(name);
}

// ?scene=full or ?scene=light overrides the choice on any device.
async function pickScene() {
  const wanted = params.get("scene") ?? (TABLET || !hasGraphicsCard() ? "light" : "full");
  if (wanted === "light") {
    const head = await fetch("scene-light.ply", { method: "HEAD" }).catch(() => null);
    if (head?.ok) return { url: "scene-light.ply", label: "light" };
  }
  return { url: "scene.ply", label: "full" };
}

const $ = (id) => document.getElementById(id);
const canvas = $("view");

// Say what's wrong, on a laptop whose browser can't draw this at all.
if (!document.createElement("canvas").getContext("webgl2")) {
  $("loading-text").textContent =
    "This browser can't draw 3D here. Try Chrome or Edge, with graphics acceleration turned on.";
  throw new Error("No WebGL 2");
}
// On a laptop with two graphics chips, ask for the faster one.
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: false,
  powerPreference: "high-performance",
});
// Rendering every splat at full high-DPI resolution is the main cost; 1 pixel per CSS pixel is enough.
renderer.setPixelRatio(RES);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 200);
scene.add(new SparkRenderer({ renderer, lodSplatCount: LOD_SPLATS }));

// Turn the scene upright once here, and put everything in scene coordinates inside `root`, so
// file coordinates can be used as they are. Scenes name their up direction in the assets file.
const root = new THREE.Group();
root.rotation.x = Math.PI; // Equipment Room's +y points down, the default until the file loads.
// Tracking (xr.js) moves the whole map through this group, so the device's real position lands
// in the right place. Without tracking it stays at identity.
const xrOffset = new THREE.Group();
scene.add(xrOffset);
xrOffset.add(root);

const controls = new SparkControls({ canvas });
// Spark turns the camera with Insert and Delete; Delete deletes the selected object here instead.
delete controls.fpsMovement.keycodeRotateMapping.Delete;
delete controls.fpsMovement.keycodeRotateMapping.Insert;
const phone = setupPhone({
  camera,
  button: $("phone"),
  joystick: $("joystick"),
  onMessage: (msg) => ($("status").textContent = msg),
});
// Walk mode keeps to the walkable floor; Fly goes anywhere.
const walkFloor = setupWalkable({ root, camera });
const raycaster = new THREE.Raycaster();
const objects = []; // { asset, box, pick, label, center, yaw, baseSize }
const pacing = setupPacing({
  renderer,
  camera,
  baseRes: RES,
  adaptive: ADAPTIVE,
  auto: !params.has("res") && !ADAPTIVE,
  isBusy: () =>
    phone.enabled ||
    Boolean(objectLayer?.state.moving) ||
    Boolean(adder?.state.active) ||
    Boolean(route?.state.walking) ||
    tracking.state.active,
  isDragging: () => Boolean(objectLayer?.state.moving?.dragging),
  isAnimated: () => Boolean(route?.state.route || flight || alerts?.isActive()),
});
let walk = true;
let flight = null; // the camera on its way to an object's best view
let tour = null;
let stages = null; // darkness, simple BIM, blob BIM, point cloud, real view
let eyeY = EYE_HEIGHT;
let startPos = new THREE.Vector3(0, EYE_HEIGHT, 0);
let startTurn = new THREE.Quaternion(); // which way you face at the start
let objectLayer = null;
let bim = null;
let route = null;
let plan = null;
let objectList = null;
let alerts = null;
let filters = null;
let selected = null;
let boxesOn = true;
let range = Number(params.get("range") ?? 3);
const highlight = setupHighlight({
  root,
  objectLayer: () => objectLayer,
  onMessage: (message) => ($("status").textContent = message),
});

const FRAME_ORDER = 5;
const FRAME_FACES = new THREE.MeshBasicMaterial({
  colorWrite: false,
  transparent: true, // Drawn with the scan's pass, after it, so it can't punch holes in the scan.
  polygonOffset: true, // Slightly behind a frame's own lines, so that they still show.
  polygonOffsetFactor: 1,
  polygonOffsetUnits: 1,
});

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

function kind(asset) {
  if (asset.mapping?.tag === faultTag) return "fault";
  return asset.mapping ? "mapped" : "plain";
}

// Links made by rule aren't real identities, so they're shown as a question.
// A link made by rule or by eye is a guess, so it reads as a question.
function name(asset) {
  const link = asset.mapping;
  if (!link) return asset.name || asset.label;
  const method = link.method ?? "";
  const guess = method.startsWith("procedural") || method.includes("unconfirmed");
  return guess ? `${link.tag}?` : link.tag;
}

function addAsset(asset) {
  const min = new THREE.Vector3(...asset.bbox_min);
  const max = new THREE.Vector3(...asset.bbox_max);
  const size = max.clone().sub(min);
  const mid = min.clone().add(max).multiplyScalar(0.5);
  const geom = new THREE.BoxGeometry(size.x, size.y, size.z);

  // Frames are drawn after the scan, so splats can't dim them. The invisible faces come first, and
  // hide lines behind them: a frame's own back edges, and any frame further away.
  const box = new THREE.LineSegments(
    new THREE.EdgesGeometry(geom),
    new THREE.LineBasicMaterial({
      color: kind(asset) === "fault" ? FAULT_COLOR : colorForLabel(asset.label),
      transparent: true,
    }),
  );
  box.renderOrder = FRAME_ORDER + 1;
  box.position.copy(mid);
  const faces = new THREE.Mesh(geom, FRAME_FACES);
  faces.renderOrder = FRAME_ORDER;
  box.add(faces);
  root.add(box);

  // Invisible solid box, so taps and the crosshair can hit the object.
  // Two-sided, so a pick ray also finds where it leaves the box (see pick.js).
  const pick = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide }));
  pick.position.copy(mid);
  pick.userData.index = objects.length;
  root.add(pick);

  const label = document.createElement("div");
  label.className = `label ${kind(asset)}`;
  $("labels").append(label);

  const volume = Math.max(size.x * size.y * size.z, 1e-6);
  objects.push({
    asset,
    box,
    pick,
    label,
    volume,
    center: new THREE.Vector3(...asset.center),
    yaw: asset.yaw ?? 0,
    baseSize: size.clone(),
  });
}

// Live condition from the backend, for objects linked to an Excel record.
async function showCondition(obj) {
  $("info-condition").replaceChildren();
  if (!obj.asset.mapping) return;
  try {
    const response = await fetch(`/api/assets/${encodeURIComponent(obj.asset.object_id)}`);
    if (!response.ok || selected !== obj) return;
    const condition = (await response.json()).condition;
    if (!condition) return;
    const text = [
      condition.issue_summary,
      `health ${condition.health_score}`,
      `urgency ${condition.urgency}`,
      condition.recommended_next_check && `next: ${condition.recommended_next_check}`,
    ].filter(Boolean);
    $("info-condition").textContent = text.join(" · ");
  } catch {
    // Without a backend, the panel still shows what the scene files know.
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function showInfo(obj) {
  const a = obj.asset;
  const m = a.mapping;
  const rows = [
    ["Type", a.label],
    ["Label grade", a.label_grade],
    ["Suggested", a.label === "object" ? a.suggested_label : undefined],
    // A reviewed type comes with what was seen, which says more than the model's reason.
    ["Type checked", a.label_was ? `${a.label_was} → ${a.label}` : null],
    ["Why", a.label_evidence || a.label_reason],
    ["Label confidence", a.label_grade ? undefined : a.label_confidence?.toFixed(2)],
    ["Mobility", a.mobility],
    ["Mobility reason", a.mobility_reason],
    ["Name", a.name],
    ["Object", a.object_id],
    ["Tag", m?.tag ?? "not mapped"],
    ["Asset", m?.asset_id],
    ["Mapped by", m ? `${m.method}, confidence ${m.confidence}` : undefined],
  ].filter(([, v]) => v !== undefined);
  const link = !m
    ? "no record linked"
    : name(a).endsWith("?")
      ? "link to its record not confirmed"
      : "linked to its record";
  const urgent = kind(a) === "fault" ? "needs attention · " : "";
  const origin = a.copied_name ? `copy of ${a.copied_name} · own ID ${a.object_id}` : link;
  $("info-head").replaceChildren();
  const title = document.createElement("h2");
  title.textContent = name(a);
  const note = document.createElement("p");
  note.className = "sub";
  note.textContent = `${a.label} · ${urgent}${origin}`;
  $("info-head").append(title, note);
  $("rename-object").hidden = Boolean(m);
  $("rename-form").hidden = true;
  $("info-body").innerHTML =
    "<dl>" + rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("") + "</dl>";
  selected = obj;
  highlight.select(obj);
  bim?.selectObject(obj);
  $("move-actions").hidden = a.mobility !== "movable" || !objectLayer;
  $("cant-move").hidden = a.mobility === "movable";
  $("cant-move").textContent =
    a.mobility === "fixed"
      ? "This is fixed, so it can't be moved."
      : "Not known to be movable, so moving is off.";
  $("route-here").hidden = !route;
  $("open-dashboard").hidden = !m?.asset_id;
  $("split-object").hidden = !route || Boolean(m);
  $("combine-object").hidden = !route || Boolean(m);
  $("info-fix").hidden = $("split-object").hidden;
  $("delete-confirm").hidden = true;
  $("ask").hidden = false;
  showCondition(obj);
  $("copilot").hidden = true;
  $("info").hidden = false;
  copilot.refresh();
}
// A tap on the scene opens a window, and the browser then sends its own click to the same spot.
// That click would land on the new window and close it at once (or press one of its buttons), so
// windows ignore clicks that arrive just after a tap on the scene.
const GHOST_CLICK_MS = 500;
let lastSceneTap = 0;

function ignoreGhostClicks(panel) {
  panel.addEventListener(
    "click",
    (event) => {
      if (performance.now() - lastSceneTap < GHOST_CLICK_MS) {
        event.stopPropagation();
        event.preventDefault();
      }
    },
    true, // capture: runs before the window's own buttons see the click
  );
}
ignoreGhostClicks($("info"));
ignoreGhostClicks($("copilot"));
$("info-close").onclick = () => {
  $("info").hidden = true;
  hideManipBar();
};

async function routeTo(obj) {
  $("info").hidden = true;
  hideManipBar();
  $("status").textContent = `Planning a route to ${name(obj.asset)}...`;
  const found = await route.plan({ asset: obj.asset, center: obj.center, name: name(obj.asset) });
  $("follow").hidden = !found;
  $("clear-route").hidden = !found;
  $("follow").textContent = "Walk route";
  selected = obj;
  highlight.select(obj);
  return found;
}
$("route-here").onclick = () => selected && routeTo(selected);

// The selected object's record as charts. Drawn by the backend, so it needs make api.
$("open-dashboard").onclick = () => {
  if (!selected) return;
  const image = $("dashboard-image");
  const id = encodeURIComponent(selected.asset.object_id);
  $("dashboard-status").textContent = "Drawing the dashboard...";
  image.hidden = true;
  image.removeAttribute("src"); // or the last device's dashboard shows first
  image.onload = () => {
    $("dashboard-status").textContent = "";
    image.hidden = false;
  };
  image.onerror = () => {
    $("dashboard-status").textContent = "Couldn't draw the dashboard. Is make api running?";
  };
  image.src = `/api/assets/${id}/dashboard.png`;
  $("dashboard").hidden = false;
};
$("dashboard-close").onclick = () => ($("dashboard").hidden = true);
// A click beside the charts closes them too.
$("dashboard").addEventListener("click", (event) => {
  if (event.target === $("dashboard")) $("dashboard").hidden = true;
});
$("duplicate-object").onclick = () => selected && duplicateObject(selected);
$("delete-object").onclick = askToDelete;
$("forget-object").onclick = () => selected && forgetObject(selected);
$("rename-object").onclick = () => {
  $("rename-form").hidden = false;
  $("rename-input").value = selected?.asset.name ?? "";
  $("rename-input").focus();
  $("rename-input").select();
};
$("rename-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (selected && $("rename-input").value.trim()) renameObject(selected, $("rename-input").value);
});
$("delete-cancel").onclick = () => ($("delete-confirm").hidden = true);
$("delete-yes").onclick = () => selected && deleteObject(selected);
function focusOn(object) {
  selected = object;
  highlight.select(object);
  bim?.selectObject(object);
}

const FLIGHT_MS = 1100;
// Glide the camera to a spot, looking at a point. Both are in world coordinates.
function flyTo(position, lookAt) {
  const look = new THREE.Matrix4().lookAt(position, lookAt, camera.up);
  flight = {
    from: camera.position.clone(),
    fromTurn: camera.quaternion.clone(),
    to: position.clone(),
    toTurn: new THREE.Quaternion().setFromRotationMatrix(look),
    started: performance.now(),
  };
  pacing.wake();
  return new Promise((resolve) => (flight.done = resolve));
}

function updateFlight(now) {
  const t = Math.min((now - flight.started) / FLIGHT_MS, 1);
  const eased = t * t * (3 - 2 * t);
  camera.position.lerpVectors(flight.from, flight.to, eased);
  camera.quaternion.slerpQuaternions(flight.fromTurn, flight.toTurn, eased);
  if (t === 1) {
    const { done } = flight;
    flight = null;
    done();
  }
}

// Go to where an object is best seen, and select it.
async function goLookAt(object) {
  if (route?.state.walking) $("follow").click();
  showInfo(object);
  const look = root.localToWorld(object.center.clone());
  const reply = await fetch(`/api/objects/${object.asset.object_id}/view`)
    .then((response) => (response.ok ? response.json() : null))
    .catch(() => null);
  let spot;
  if (reply?.from) {
    spot = root.localToWorld(new THREE.Vector3(...reply.from));
  } else {
    // No floor map: step back towards where we are now.
    const back = camera.position.clone().sub(look).setY(0);
    spot = look.clone().add(back.normalize().multiplyScalar(2));
  }
  spot.y = eyeY;
  walkFloor.forget();
  await flyTo(spot, look);
  if (reply?.from && !reply.clear) {
    $("status").textContent = `Something may be in the way of ${name(object.asset)}`;
  }
  return { ok: true, message: "" };
}

// Val's answers can point at objects, or ask for a route. Returns what went wrong, if anything.
async function runValActions(actions) {
  const find = (id) => objects.find((o) => o.asset.object_id === id && !o.gone);
  let problem = null;
  for (const action of actions) {
    // Something asked for out loud or typed: the same code as the button.
    if (action.type === "viewer") {
      try {
        const result = await commandHandlers()[action.action](action.args);
        if (result?.ok === false) problem = result.message || result.reason || "That didn't work.";
      } catch (error) {
        problem = error.message;
      }
      // People know devices by name, not by the scene's object IDs.
      const object = find(action.args.object_id);
      if (problem && object) problem = problem.replaceAll(object.asset.object_id, name(object.asset).replace(/\?$/, ""));
      continue;
    }
    const object = find(action.object_id);
    if (!object) continue;
    if (action.type === "highlight") focusOn(object);
    if (action.type === "navigate") {
      const found = await routeTo(object);
      if (!found) problem = `I couldn't plan the route: ${$("status").textContent}`;
      else if (window.innerWidth < 700) $("copilot").hidden = true;
    }
  }
  return problem;
}

const copilot = setupCopilot({
  panel: $("copilot"),
  form: $("copilot-form"),
  input: $("copilot-input"),
  messages: $("val-messages"),
  suggestions: $("val-suggestions"),
  context: $("val-context"),
  close: $("copilot-close"),
  micButton: $("val-mic"),
  getObject: () => selected,
  clearObject: () => {
    selected = null;
    highlight.select(null);
    bim?.selectObject(null);
  },
  nameOf: (object) => name(object.asset),
  getFaultTag: () => faultTag,
  onActions: runValActions,
});
$("open-copilot").onclick = () => {
  $("info").hidden = true;
  copilot.open();
};
$("ask").onclick = () => {
  $("info").hidden = true;
  const linked = selected?.asset.mapping;
  copilot.open(linked ? "What's wrong with it, and what should I check first?" : "What is this?");
};

for (const [text, color] of LEGEND) {
  const item = document.createElement("span");
  const swatch = document.createElement("i");
  swatch.style.background = `#${color.toString(16).padStart(6, "0")}`;
  item.append(swatch, text);
  $("frame-legend").append(item);
}

// The main buttons stay few. Everything else waits behind Actions.
function showMenu(open) {
  $("more-menu").hidden = !open;
  $("more").setAttribute("aria-expanded", String(open));
}
$("more").onclick = () => showMenu($("more-menu").hidden);
$("more-menu").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button && !("stay" in button.dataset)) showMenu(false);
});
canvas.addEventListener("pointerdown", () => showMenu(false));

// Messages fade once they've been read, so they don't sit over the view. A warning stays.
const STATUS_TIME = 6000;
let statusTimer = null;
new MutationObserver(() => {
  $("hud").classList.remove("quiet");
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    if (!$("hud").classList.contains("blocked")) $("hud").classList.add("quiet");
  }, STATUS_TIME);
}).observe($("status"), { childList: true, characterData: true, subtree: true });

const adder = setupAddObject({
  canvas,
  root,
  camera,
  render: () => renderer.render(scene, camera),
  ui: {
    button: $("add-object"),
    frame: $("select-frame"),
    title: $("add-title"),
    restRow: $("add-rest"),
    restLabel: $("add-rest-label"),
    restMobility: $("add-rest-mobility"),
    panel: $("add-panel"),
    label: $("add-label"),
    mobility: $("add-mobility"),
    notes: $("add-notes"),
    warning: $("add-warning"),
    config: $("add-config"),
    bigger: $("add-bigger"),
    smaller: $("add-smaller"),
    save: $("add-save"),
    cancel: $("add-cancel"),
  },
  onMessage: (message) => ($("status").textContent = message),
  onSplit: async (parent, parts) => {
    const heirs = parts.map((part) => {
      addAsset(part);
      objects.at(-1).addedByOperator = true;
      return objects.at(-1);
    });
    hideObject(parent, heirs);
    parent.splitAway = true;
    selected = objects.at(-2);
    highlight.select(selected);
    const names = parts.map((part) => `${part.object_id} (${part.label})`).join(" and ");
    const text = `Split into ${names}, not confirmed`;
    $("status").textContent = text;
    if (route?.state.target) {
      await route.plan(route.state.target, route.state.start);
      $("status").textContent = `${text}. ${$("status").textContent}`;
    }
  },
  onCombine: async (first, other, combined) => {
    addAsset(combined);
    selected = objects.at(-1);
    selected.addedByOperator = true;
    for (const object of [first, other]) {
      hideObject(object, [selected]);
      object.splitAway = true;
    }
    highlight.select(selected);
    const text = `Combined into ${combined.object_id} (${combined.label}), not confirmed`;
    $("status").textContent = text;
    if (route?.state.target) {
      await route.plan(route.state.target, route.state.start);
      $("status").textContent = `${text}. ${$("status").textContent}`;
    }
  },
  onSaved: async (asset) => {
    addAsset(asset);
    const added = objects.at(-1);
    added.addedByOperator = true;
    selected = added;
    highlight.select(added);
    const added_text = `Added ${asset.object_id}: ${asset.label}, not confirmed`;
    $("status").textContent = added_text;
    if (route?.state.target) {
      await route.plan(route.state.target, route.state.start);
      $("status").textContent = `${added_text}. ${$("status").textContent}`;
    }
  },
});
$("add-object").onclick = () => adder.start();
$("combine-object").onclick = () => {
  if (!selected) return;
  $("info").hidden = true;
  adder.startCombine(selected);
};
$("split-object").onclick = () => {
  if (!selected) return;
  $("info").hidden = true;
  adder.startSplit(selected);
};

function hideObject(object, heirs) {
  objectLayer?.dropPiece(object, heirs);
  object.gone = true;
  object.box.visible = false;
  object.pick.layers.disable(0);
  object.label.style.display = "none";
}

// Undo removes operator-added objects too, because the backend's reset forgets them.
function removeAdded() {
  // The backend's reset forgets names too, apart from what the scan's objects came with.
  for (const object of objects) if (!object.addedByOperator) delete object.asset.name;
  for (const object of objects) {
    if (object.addedByOperator) {
      object.addedByOperator = false;
      hideObject(object);
    }
  }
  // After that, as these may have been showing a piece the objects above inherited.
  for (const object of objects) {
    if (object.splitAway) {
      // The backend's reset brings back whatever was split, combined or deleted.
      object.splitAway = false;
      object.gone = false;
      object.pick.layers.enable(0);
      objectLayer?.unerase(object);
      objectLayer?.restorePiece(object);
    }
  }
}

function deselect() {
  selected = null;
  highlight.select(null);
  bim?.selectObject(null);
  $("info").hidden = true;
  copilot.refresh();
}

// Delete asks first, in the panel. Undo (or Ctrl+Z) brings an object back.
async function renameObject(object, text) {
  const response = await fetch("/api/changes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ op: "rename", object_id: object.asset.object_id, details: { name: text } }),
  });
  const reply = await response.json().catch(() => ({}));
  if (!response.ok) {
    $("status").textContent = `Couldn't name it: ${reply.detail ?? `error ${response.status}`}`;
    return { ok: false, message: reply.detail };
  }
  object.asset.name = text.trim();
  bim?.rename(object);
  if (selected === object) showInfo(object);
  $("status").textContent = `Named ${object.asset.name}.`;
  return { ok: true };
}

function askToDelete() {
  if (!selected) return;
  const tag = selected.asset.mapping?.tag;
  $("delete-question").textContent = tag
    ? `Delete ${name(selected.asset)} from the viewer? It's linked to the record for ${tag}.`
    : `Delete this ${selected.asset.label} from the viewer?`;
  $("delete-confirm").hidden = false;
}

async function deleteObject(object) {
  const text = name(object.asset);
  const routed = route?.state.target?.asset === object.asset;
  await objectLayer.erase(object);
  hideObject(object);
  object.splitAway = !object.addedByOperator;
  deselect();
  if (routed) $("clear-route").click();
  objectLayer.recordRemoval(object);
  $("status").textContent = `Deleted ${text}. Undo (Ctrl+Z) brings it back.`;
}

// Remove info only: for a junk detection, such as a stray bucket. Its box, label and data go, but
// the scan still shows it, and a movable one still blocks routes. Undo brings the info back.
function forgetObject(object) {
  const text = name(object.asset);
  const routed = route?.state.target?.asset === object.asset;
  // Not hideObject: that drops the object's splats too, and these stay exactly where they are.
  object.gone = true;
  object.box.visible = false;
  object.pick.layers.disable(0);
  object.label.style.display = "none";
  object.splitAway = !object.addedByOperator;
  deselect();
  if (routed) $("clear-route").click();
  objectLayer.recordRemoval(object, true);
  $("status").textContent = `Removed the info for ${text}; it stays in the scan. Ctrl+Z undoes it.`;
}

// The first free spot beside an object, as a copy mustn't land on top of anything.
async function freeSpotBeside(object) {
  const { bbox_min: low, bbox_max: high } = object.asset;
  const size = Math.max(Math.abs(high[0] - low[0]), Math.abs(high[2] - low[2]));
  for (const reach of [1.2, 1.8, 2.6]) {
    for (let step = 0; step < 8; step++) {
      const angle = (step * Math.PI) / 4;
      const spot = [
        object.center.x + Math.cos(angle) * (size * reach + 0.1),
        object.center.y,
        object.center.z + Math.sin(angle) * (size * reach + 0.1),
      ];
      if ((await checkMove(object, spot, object.yaw || 0)).ok) return spot;
    }
  }
  return null;
}

async function duplicateObject(object) {
  $("status").textContent = `Copying ${name(object.asset)}...`;
  const position = await freeSpotBeside(object);
  if (!position) {
    $("status").textContent = "There's no free spot beside it for a copy.";
    return { ok: false, message: $("status").textContent };
  }
  try {
    const change = await fetch("/api/changes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "duplicate", object_id: object.asset.object_id, position }),
    }).then((response) => response.json());
    const id = encodeURIComponent(change.parts[0]);
    const asset = await fetch(`/api/assets/${id}`).then((response) => response.json());
    addAsset(asset);
  } catch (error) {
    $("status").textContent = `Couldn't copy it: ${error.message}`;
    return { ok: false, message: $("status").textContent };
  }
  const copy = objects.at(-1);
  copy.addedByOperator = true;
  objectLayer.placeAt(copy, copy.asset.center, copy.asset.yaw ?? 0);
  objectLayer.addCopy(copy);
  showInfo(copy);
  if (route?.state.target) await route.plan(route.state.target, route.state.start);
  $("status").textContent = `Copied as ${name(copy.asset)}, with its own ID ${copy.asset.object_id}.`;
}

// Esc, or the back button on a phone: one step back, the most recent thing first.
function goBack() {
  if (!$("dashboard").hidden) $("dashboard").hidden = true;
  else if (!$("more-menu").hidden) showMenu(false);
  else if (!$("rename-form").hidden) $("rename-form").hidden = true;
  else if (!$("help-panel").hidden) $("help-panel").hidden = true;
  else if (!$("dashboard").hidden) $("dashboard").hidden = true;
  else if (tour?.state.running) tour.stop();
  else if (stages?.state.stage === "dark") stages.set("real");
  else if (!$("delete-confirm").hidden) $("delete-confirm").hidden = true;
  else if (!$("add-panel").hidden || adder.state.active) $("add-cancel").click();
  else if (objectLayer?.state.moving) $("manip-done").click();
  else if (route?.state.walking) $("follow").click();
  else if (!$("copilot").hidden) $("copilot-close").click();
  else if (plan?.state.expanded) plan.collapse();
  else if (!$("filter-panel").hidden) $("filter-panel").hidden = true;
  else if (objectList?.state.open) objectList.close();
  else if (selected || !$("info").hidden) deselect();
  else return false;
  return true;
}
// Keyboard shortcuts. Never while typing into Val or a name box, so letters stay letters.
// WASD, Q/E and the arrows stay with the camera.
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    goBack();
    return;
  }
  if (isTyping() || event.altKey) return;
  const press = (id) => {
    const button = $(id);
    if (!button || button.hidden || button.disabled) return false;
    button.click();
    return true;
  };
  const key = event.key.toLowerCase();
  const command = event.ctrlKey || event.metaKey;
  let handled = false;
  if (key === "?") {
    $("help-panel").hidden = !$("help-panel").hidden;
    handled = true;
  } else if (key.startsWith("arrow") && objectLayer?.state.moving && !command) {
    nudgeObject(key, event.shiftKey);
    handled = true;
  } else if (command && key === "z") handled = press("undo-last");
  else if (command) return; // leave the browser's own shortcuts alone
  else if (key === "delete" || key === "backspace") {
    if (selected) handled = $("delete-confirm").hidden ? press("delete-object") : press("delete-yes");
  } else if (key === "enter") {
    if (!$("delete-confirm").hidden) handled = press("delete-yes");
    else if (!$("manip-bar").hidden) handled = press("manip-done");
  } else if (key === "m" && selected) handled = press("move");
  else if (key === "r" && !$("manip-bar").hidden) handled = press("manip-mode-rotate");
  else if (key === "c" && selected) handled = press("duplicate-object");
  else if (key === "n" && selected) handled = press("rename-object");
  else if (key === "pageup" && !$("manip-bar").hidden) handled = press("manip-raise");
  else if (key === "pagedown" && !$("manip-bar").hidden) handled = press("manip-lower");
  else if (key === "f") handled = press("mode");
  else if (key === "g") handled = press("go-fault");
  else if (key === "b") handled = press("next-view");
  else if (key === "l") handled = press("open-list");
  else if (key === "t") handled = press("open-filters");
  else if (key === "v") {
    // Talk to Val from anywhere.
    copilot.open();
    copilot.listen();
    handled = true;
  }
  if (handled) event.preventDefault();
});
// One spare history entry catches the back button. With nothing left to close, it leaves the page.
history.pushState({ viewer: true }, "");
window.addEventListener("popstate", () => {
  if (goBack()) history.pushState({ viewer: true }, "");
  else history.back();
});
$("go-fault").onclick = () => {
  const fault = objects.find((o) => kind(o.asset) === "fault");
  if (fault) routeTo(fault);
  else $("status").textContent = `No object is mapped to ${faultTag}`;
};
$("profile").onclick = async () => {
  const next = route.state.profile === "person" ? "robot" : "person";
  $("profile").textContent = next[0].toUpperCase() + next.slice(1);
  const found = await route.setProfile(next);
  if (route.state.target) {
    $("follow").hidden = !found;
    $("clear-route").hidden = !found;
  }
};
$("follow").onclick = () => {
  if (route.state.walking) route.stopWalking();
  else if (route.startWalking()) walk = true;
};
$("clear-route").onclick = () => {
  route.clear();
  $("follow").hidden = true;
  $("clear-route").hidden = true;
};

// Manipulation controls (Move / Rotate on floor)
function showManipBar(mode) {
  $("manip-bar").hidden = false;
  $("manip-mode-move").classList.toggle("active", mode === "move");
  $("manip-mode-rotate").classList.toggle("active", mode === "rotate");
  $("manip-title").textContent = name(selected.asset);
  updateStatusForMode(mode);
}

// Hiding the bar also leaves move mode. Otherwise the next drag would move the object.
function hideManipBar() {
  $("manip-bar").hidden = true;
  objectLayer?.finishManipulation();
}

function updateStatusForMode(mode) {
  if (!selected) return;
  if (mode === "rotate") {
    $("status").textContent = `Rotate ${name(selected.asset)}: Arrow keys or drag across screen, tap 45°, or twist with 2 fingers`;
  } else {
    $("status").textContent = `Move ${name(selected.asset)}: Arrow keys or drag along the floor · Page Up and Down for height · R to rotate`;
  }
}

$("move").onclick = () => {
  if (objectLayer?.startMove(selected)) {
    $("info").hidden = true;
    showManipBar("move");
  }
};
// Arrow keys, only while moving or rotating an object. Up is away from you and right is to your
// right, on the floor, wherever you're facing. Shift goes further. Each press is checked and saved.
const NUDGE_M = 0.05;
const NUDGE_FAR_M = 0.25;
const NUDGE_TURN = Math.PI / 36; // 5 degrees
const NUDGE_FAR_TURN = Math.PI / 12; // 15 degrees
let nudging = false;
async function nudgeObject(key, far) {
  const object = objectLayer?.state.moving?.object;
  if (!object || nudging) return;
  const yaw = object.yaw || 0;
  nudging = true;
  try {
    let result;
    if ($("manip-mode-rotate").classList.contains("active")) {
      if (key !== "arrowleft" && key !== "arrowright") return;
      const sign = key === "arrowleft" ? -1 : 1;
      const step = far ? NUDGE_FAR_TURN : NUDGE_TURN;
      result = await objectLayer.moveTo(object, undefined, yaw + sign * step);
    } else {
      const ahead = camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize();
      const right = new THREE.Vector3().crossVectors(ahead, camera.up).normalize();
      const metres = far ? NUDGE_FAR_M : NUDGE_M;
      const direction = { arrowup: ahead, arrowdown: ahead.clone().negate(), arrowright: right, arrowleft: right.clone().negate() }[key];
      const toScene = new THREE.Matrix4().copy(root.matrixWorld).invert();
      const shift = direction.clone().transformDirection(toScene).multiplyScalar(metres);
      result = await objectLayer.moveTo(object, object.center.clone().add(shift).toArray(), yaw);
    }
    if (!result.ok) $("status").textContent = result.message;
  } finally {
    nudging = false;
  }
}

// On the floor, from where you look: forward is away from you, right is to your right.
function floorDirection(direction) {
  const ahead = camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize();
  const right = new THREE.Vector3().crossVectors(ahead, camera.up).normalize();
  const world = {
    forward: ahead,
    back: ahead.clone().negate(),
    right,
    left: right.clone().negate(),
  }[direction];
  const toScene = new THREE.Matrix4().copy(root.matrixWorld).invert();
  return world.clone().transformDirection(toScene);
}

const MOVE_STEP_M = 0.1; // how finely a move looks for the furthest free spot
const MOVE_CHECKS = 30; // checks at a time, so a long move can't flood the backend
const MOVE_MAX_M = 15; // further than that leaves the room anyway

// Move an object a measured distance. If the end is blocked, it goes as far as it can.
async function moveBy(object, metres, direction) {
  if (direction === "up" || direction === "down") {
    const result = await objectLayer.raise(object, direction === "up" ? metres : -metres);
    return result.ok ? { ok: true, message: "" } : result;
  }
  const step = floorDirection(direction);
  const yaw = object.yaw || 0;
  const start = object.center.clone();
  const at = (distance) => start.clone().addScaledVector(step, distance).toArray();
  const wanted = Math.min(metres, MOVE_MAX_M);
  // Coarse first, then finer between the furthest free spot and the next one.
  const tryAlong = async (from, to) => {
    const count = Math.max(1, Math.min(MOVE_CHECKS, Math.round((to - from) / MOVE_STEP_M)));
    const distances = Array.from({ length: count }, (_, i) => from + ((to - from) * (i + 1)) / count);
    const checks = await Promise.all(distances.map((d) => checkMove(object, at(d), yaw)));
    const last = checks.findLastIndex((check) => check.ok);
    return { distances, checks, last };
  };
  const coarse = await tryAlong(0, wanted);
  let furthest = coarse.last >= 0 ? coarse.distances[coarse.last] : 0;
  const next = coarse.distances[coarse.last + 1];
  if (next !== undefined && next - furthest > MOVE_STEP_M * 1.5) {
    const fine = await tryAlong(furthest, next);
    if (fine.last >= 0) furthest = fine.distances[fine.last];
  }
  const checks = coarse.checks;
  if (furthest === 0) {
    return { ok: false, message: `${name(object.asset)} can't move ${direction}: ${checks[0].reason}` };
  }
  const result = await objectLayer.moveTo(object, at(furthest), yaw);
  if (!result.ok) return result;
  const message =
    furthest < metres - 1e-6 && checks.at(-1).reason
      ? `Moved ${name(object.asset)} ${furthest.toFixed(1)} m ${direction}, as far as it can go: ${checks.at(-1).reason}`
      : `Moved ${name(object.asset)} ${metres} m ${direction}.`;
  $("status").textContent = message;
  return { ok: true, message };
}

// Find the object someone means by "P-005", "Bob", "the cart" or "the other chair": a tag or a
// given name first, then the nearest object of that type that isn't the one being moved.
function findNamed(text, besides) {
  const words = text.toLowerCase().replace(/^(?:the|a|an|that|this)\s+/, "");
  const other = words.replace(/^other\s+/, "");
  const live = objects.filter((o) => !o.gone && o !== besides);
  const exact = live.find(
    (o) =>
      (o.asset.mapping?.tag ?? "").toLowerCase() === other ||
      (o.asset.name ?? "").toLowerCase() === other ||
      o.asset.object_id === other,
  );
  if (exact) return exact;
  const singular = other.replace(/e?s$/, "");
  const sameType = live.filter((o) => {
    const label = (o.asset.label ?? "").toLowerCase();
    return label === other || label === singular || label.split(" ").includes(singular);
  });
  const distance = (o) => o.center.distanceTo(besides.center);
  return sameType.sort((a, b) => distance(a) - distance(b))[0] ?? null;
}

const NEAR_GAP_M = 0.05; // space left between the two
const NEAR_SEARCH_M = 2; // how far beyond touching to look for a free spot
const NEAR_ANGLES = 16;

// Move an object as close as it can go to another, on the side nearest where it is now.
async function moveNear(object, text) {
  const other = findNamed(text, object);
  if (!other) return { ok: false, message: `I can't find ${text} in the room.` };
  const half = (o) =>
    Math.hypot(o.asset.bbox_max[0] - o.asset.bbox_min[0], o.asset.bbox_max[2] - o.asset.bbox_min[2]) / 2;
  const yaw = object.yaw || 0;
  const touching = half(object) * 0.75 + half(other) * 0.75 + NEAR_GAP_M;
  for (let reach = touching; reach <= touching + NEAR_SEARCH_M; reach += MOVE_STEP_M) {
    const spots = Array.from({ length: NEAR_ANGLES }, (_, i) => {
      const angle = (i / NEAR_ANGLES) * Math.PI * 2;
      return [other.center.x + Math.cos(angle) * reach, object.center.y, other.center.z + Math.sin(angle) * reach];
    });
    const checks = await Promise.all(spots.map((spot) => checkMove(object, spot, yaw)));
    const free = spots.filter((_, i) => checks[i].ok);
    if (!free.length) continue;
    const here = object.center;
    free.sort((a, b) => Math.hypot(a[0] - here.x, a[2] - here.z) - Math.hypot(b[0] - here.x, b[2] - here.z));
    const result = await objectLayer.moveTo(object, free[0], yaw);
    if (!result.ok) return result;
    // Two chairs are both "chair", so say which one.
    const which = name(other.asset) === name(object.asset) ? ` (${other.asset.object_id})` : "";
    const message = `Moved ${name(object.asset)} next to ${name(other.asset)}${which}.`;
    $("status").textContent = message;
    return { ok: true, message };
  }
  return { ok: false, message: `There's no free spot near ${name(other.asset)}.` };
}

// Height: 10 cm a press. The object being moved, or the selected one.
const RAISE_STEP = 0.1;
async function raiseObject(metres) {
  const object = objectLayer?.state.moving?.object ?? selected;
  if (!object) return;
  const result = await objectLayer.raise(object, metres);
  $("status").textContent = result.ok
    ? `${name(object.asset)} ${metres > 0 ? "raised" : "lowered"} ${Math.abs(metres) * 100} cm`
    : result.message;
}
$("open-help").onclick = () => ($("help-panel").hidden = !$("help-panel").hidden);
$("help-close").onclick = () => ($("help-panel").hidden = true);
$("manip-raise").onclick = () => raiseObject(RAISE_STEP);
$("manip-lower").onclick = () => raiseObject(-RAISE_STEP);

$("manip-mode-move").onclick = () => {
  objectLayer?.setMode("move");
  showManipBar("move");
};
$("manip-mode-rotate").onclick = () => {
  objectLayer?.setMode("rotate");
  showManipBar("rotate");
};
$("manip-turn-left").onclick = () => {
  objectLayer?.turnObject(-Math.PI / 4);
};
$("manip-turn-right").onclick = () => {
  objectLayer?.turnObject(Math.PI / 4);
};
$("manip-done").onclick = () => {
  objectLayer?.finishManipulation();
  hideManipBar();
};

function hit(ndc) {
  if (stages?.state.stage === "dark") return null;
  raycaster.setFromCamera(ndc, camera);
  const candidates = objects
    .filter((o) => !o.gone && o.pick.layers.isEnabled(0) && (!filters || filters.passes(o)))
    .map((o) => ({
      mesh: o.pick,
      volume: o.volume,
      thin: THIN_LABELS.has(o.asset.label),
      surface: (rc) => bim?.surfaceDistance(o, rc) ?? null,
      object: o,
    }));
  return pickFront(raycaster, candidates)?.object ?? null;
}

// A mouse shows what a tap would pick, in BIM mode and in the scan. Checked once a frame, so it
// also follows the view when the camera moves under a still mouse.
let hoverAt = null;
let hoverChanged = false;
canvas.addEventListener("pointermove", (e) => {
  const free = e.pointerType === "mouse" && e.buttons === 0;
  hoverAt = free ? { x: e.clientX, y: e.clientY } : null;
  hoverChanged = true;
});
canvas.addEventListener("pointerleave", () => {
  hoverAt = null;
  hoverChanged = true;
});
let hovering = false;
let lastHovered = null;
let lastHoverCheck = 0;
const HOVER_EVERY = 66; // milliseconds: checking every object under the mouse takes a while
// Without BIM data, or while objects are pulled apart, the scan view outlines the pick box.
const sceneHover = createHoverShell(root);
function updateHover() {
  const busy = adder.state.active || objectLayer?.state.moving;
  const inBim = Boolean(bim?.state.active);
  let found = null;
  if (hoverAt && !busy) {
    const ndc = new THREE.Vector2(
      (hoverAt.x / window.innerWidth) * 2 - 1,
      -(hoverAt.y / window.innerHeight) * 2 + 1,
    );
    if (inBim) {
      raycaster.setFromCamera(ndc, camera);
      found = bim.hover(raycaster);
    } else found = hit(ndc);
  } else if (hovering && inBim) bim.hover(null);
  const apart = objectLayer?.state.amount > 0;
  const shaped = !inBim && found && !apart && bim?.hoverObject(found);
  if (!inBim && !shaped) bim?.hoverObject(null);
  if (!inBim && found && !shaped) sceneHover.show(found.pick.geometry, found.pick.position, found.pick.quaternion);
  else sceneHover.hide();
  hovering = Boolean(found);
  canvas.style.cursor = found ? "pointer" : "";
  // The outline needs drawing, even while nothing else is being redrawn.
  if (found !== lastHovered) pacing.drawOnce();
  lastHovered = found;
}

// A short tap without dragging selects an object. Drags are camera movement.
let down = null;
canvas.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY, t: e.timeStamp }));
canvas.addEventListener("pointerup", (e) => {
  if (!down) return;
  const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
  const quick = e.timeStamp - down.t < 300;
  down = null;
  if (moved > 8 || !quick) return;
  lastSceneTap = performance.now();
  const ndc = new THREE.Vector2(
    (e.clientX / window.innerWidth) * 2 - 1,
    -(e.clientY / window.innerHeight) * 2 + 1,
  );
  if (bim?.state.active && !adder.state.active) {
    raycaster.setFromCamera(ndc, camera);
    if (!bim.pick(raycaster)) $("info").hidden = true;
    return;
  }
  const obj = hit(ndc);
  if (obj && adder.state.combining && !adder.state.other) adder.combineWith(obj);
  else if (obj) {
    if (selected !== obj && !objectLayer?.state.moving) hideManipBar();
    showInfo(obj);
  }
});

$("mode").onclick = () => {
  walk = !walk;
  $("mode").textContent = walk ? "Walk" : "Fly";
};
$("boxes").onclick = () => {
  boxesOn = !boxesOn;
  $("boxes").textContent = boxesOn ? "Boxes on" : "Boxes off";
};
$("range").textContent = `Range ${range} m`;
$("range").onclick = () => {
  range = RANGES[(RANGES.indexOf(range) + 1) % RANGES.length];
  $("range").textContent = `Range ${range} m`;
};
const tracking = setupWalkXR({
  renderer,
  scene,
  camera,
  offset: xrOffset,
  getStart: () => ({ position: startPos, floorY: eyeY - EYE_HEIGHT }),
  onMessage: (message) => ($("status").textContent = message),
});
xrSupported().then((ok) => ($("track").hidden = !ok));
$("track").onclick = async () => {
  if (tracking.state.active) return tracking.stop();
  try {
    await tracking.start();
  } catch (error) {
    $("status").textContent = `Tracking failed: ${error.message}`;
  }
};

$("reset").onclick = () => {
  if (tracking.state.active) return tracking.recenter();
  walkFloor.forget();
  camera.position.copy(startPos);
  camera.quaternion.copy(startTurn);
};

const pos = new THREE.Vector3();
// Choosing what to show looks at every object, so it runs a few times a second. Placing what's
// shown runs every frame, as labels must stay on their objects.
const CHOOSE_EVERY = 200; // milliseconds
let lastChosen = 0;
let shownLabels = [];

// A linked object says how it's doing, from its Excel record. The panel has the rest.
const CONDITION_WORDS = {
  attention_required: "attention",
  degraded: "degraded",
  watch: "watch",
  healthy: "healthy",
};
function labelText(object) {
  const record = object.condition;
  const word = CONDITION_WORDS[record?.condition_state];
  if (!word) return name(object.asset);
  const health = record.health_score == null ? "" : ` · health ${Math.round(record.health_score)}`;
  return `${name(object.asset)} · ${word}${health}`;
}

function setLabel(object, text, visible) {
  if (object.labelShown === visible && (!visible || object.labelText === text)) return;
  object.labelShown = visible;
  object.label.style.display = visible ? "block" : "none";
  if (visible && object.labelText !== text) {
    object.labelText = text;
    object.label.textContent = text;
  }
}

function placeLabels() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  for (const o of shownLabels) {
    pos.copy(o.center).applyMatrix4(root.matrixWorld).project(camera);
    const x = ((pos.x + 1) / 2) * w;
    const y = ((-pos.y + 1) / 2) * h;
    o.label.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
  }
}

function chooseLabels() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const apart = objectLayer?.state.apart;
  for (const o of objects) o.box.visible = false;

  const nearby = [];
  for (const o of objects) {
    if (o.gone) continue;
    if (bim?.state.active && !bim.shows(o)) continue;
    if (stages?.state.stage === "dark" || stages?.state.stage === "points") continue;
    const filtering = filters?.isActive();
    if (filtering && !filters.passes(o) && o !== selected) continue;
    pos.copy(o.center).applyMatrix4(root.matrixWorld);
    const dist = camera.position.distanceTo(pos);
    // Asking for "only pumps" means all of them, however far away.
    if (dist > range && !filtering) continue;
    pos.project(camera);
    const onScreen = pos.z > 0 && pos.z < 1 && Math.abs(pos.x) <= 1 && Math.abs(pos.y) <= 1;
    // Fault and mapped objects show first, background labels last.
    const rank =
      kind(o.asset) === "fault" ? 0 : kind(o.asset) === "mapped" ? 1 : BACKGROUND_LABELS.has(o.asset.label) ? 3 : 2;
    nearby.push({
      o,
      dist,
      rank,
      onScreen,
      x: ((pos.x + 1) / 2) * w,
      y: ((-pos.y + 1) / 2) * h,
      pinned: kind(o.asset) === "fault",
    });
  }

  nearby.sort((a, b) => a.rank - b.rank || a.dist - b.dist);
  const inView = nearby.filter((item) => item.onScreen);
  if (boxesOn && !apart && !stages?.isQuiet()) {
    for (const { o } of inView.slice(0, MAX_BOXES)) {
      if (!highlight.hasSurface(o)) o.box.visible = true;
    }
    for (const { o, pinned } of nearby) {
      if (pinned && !highlight.hasSurface(o)) o.box.visible = true;
    }
  }
  // A warning always shows, even past the limits or with boxes off.
  for (const o of objects) if (o.warning && !o.gone) o.box.visible = true;
  const next = new Set();
  const taken = []; // label boxes already placed on screen this round, so none overlap
  const filteringNow = filters?.isActive();
  for (const item of inView) {
    const o = item.o;
    // Unconfirmed objects keep their frame, but don't crowd the view with a generic tag.
    if (o.asset.status === "new, unconfirmed") continue;
    // Pipes, cables and unknown "object"s are everywhere: name them only when asked for.
    if (item.rank === 3 && o !== selected && !filteringNow) continue;
    if (next.size >= MAX_LABELS && !item.pinned) continue;
    const width = labelText(o).length * LABEL_CHAR_PX + LABEL_PAD_PX;
    const box = { left: item.x - width / 2, right: item.x + width / 2, top: item.y - LABEL_HEIGHT_PX, bottom: item.y };
    const overlaps = taken.some(
      (other) => box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top,
    );
    if (overlaps && !item.pinned && o !== selected) continue;
    taken.push(box);
    next.add(o);
  }
  for (const o of objects) setLabel(o, labelText(o), next.has(o) && !alerts?.isShowing(o));
  shownLabels = [...next];
}

let lastTime = 0;

// True while a text box, such as Val's chat, has the keyboard.
function isTyping() {
  const element = document.activeElement;
  return Boolean(element?.matches?.("input, textarea, select, [contenteditable='true']"));
}
let lastStep = 0;
let frames = 0;
let lastFps = performance.now();
function animate(now) {
  const following = Boolean(route?.state.walking);
  const busy = objectLayer?.state.moving || adder.state.active || following || flight;
  // Typing in the Plan screen's search box shouldn't walk the viewer around. While tracking, the
  // device's own movement moves the camera, so the other controls stay out.
  const tracked = tracking.state.active;
  // Keys typed into Val or a name box are for that box, not for walking.
  const typingNow = isTyping();
  if (!phone.enabled && !busy && !tracked && !plan?.state.expanded && !typingNow) controls.update(camera);
  const stepTime = lastStep ? (now - lastStep) / 1000 : 0;
  lastStep = now;
  if (flight) updateFlight(now);
  if (following && !tracked) route.update(stepTime);
  else if (!tracked) phone.update(stepTime);
  if (walk && !tracked) camera.position.y = eyeY;
  if (walk && !tracked && !following) walkFloor.keepOnFloor(now);
  const hoverDue = now - lastHoverCheck > HOVER_EVERY;
  if (hoverDue && (hoverChanged || (hoverAt && pacing.isMoving()))) {
    hoverChanged = false;
    lastHoverCheck = now;
    if (!plan?.state.expanded) updateHover();
  }
  if (!pacing.shouldDraw(now)) return;

  const dt = lastTime ? (now - lastTime) / 1000 : 0;
  lastTime = now;
  objectLayer?.update(dt);
  highlight.update();
  bim?.update();
  route?.animate(dt);
  if (!following && !adder.state.active) {
    const moving = objectLayer?.state.moving;
    route?.updateLive(
      moving?.dragging
        ? {
            object_id: moving.object.asset.object_id,
            position: moving.object.center.toArray(),
            yaw: moving.object.yaw || 0,
          }
        : null,
      walk,
    );
  }
  const followText = following ? "Stop" : "Walk route";
  if ($("follow").textContent !== followText) $("follow").textContent = followText;
  // Expanded, the map covers the room, so there's no need to draw that as well.
  if (!plan?.state.expanded) {
    alerts?.update(now);
    renderer.render(scene, camera);
    alerts?.placeBadges();
    tracking.update();
    if (now - lastChosen > CHOOSE_EVERY) {
      lastChosen = now;
      chooseLabels();
    }
    placeLabels();
  }
  plan?.draw(now);
  pacing.drew(now);
  frames++;
  if (DEBUG && now - lastFps > 1000) {
    const fps = Math.round((frames * 1000) / (now - lastFps));
    $("stats").textContent =
      `${fps} fps · sharpness ${pacing.stats.scale.toFixed(2)}` +
      (phone.enabled ? ` · ${phone.steps} steps` : "");
    frames = 0;
    lastFps = now;
  }
}

// The scene files only hold the original scan, and the backend holds what's changed since. Without
// this, a reloaded page shows objects at their old spots while routes avoid their new ones.
async function syncWithBackend() {
  let current;
  try {
    const response = await fetch("/api/assets");
    if (!response.ok) throw new Error(`error ${response.status}`);
    current = (await response.json()).assets;
  } catch {
    $("status").textContent = "Backend not connected: start make api. Moves won't save, no routes.";
    return;
  }
  const known = new Map(objects.map((object) => [object.asset.object_id, object]));
  if (!current.some((asset) => known.has(asset.object_id))) {
    $("status").textContent =
      "Backend has different objects from this page: pass the same ASSETS file to make web and make api.";
    return;
  }
  let changed = 0;
  const present = new Set(current.map((asset) => asset.object_id));
  const saved = await fetch("/api/changes")
    .then((response) => response.json())
    .catch(() => ({ changes: [] }));
  const removedIds = new Set(
    saved.changes
      .filter((change) => change.op === "remove" && !change.details?.keep_splats)
      .map((change) => change.object_id),
  );
  for (const object of objects) {
    if (!present.has(object.asset.object_id)) {
      hideObject(object);
      object.splitAway = true;
      if (removedIds.has(object.asset.object_id)) objectLayer.erase(object);
      changed += 1;
    }
  }
  // What's being dragged follows the pointer, and is saved when it's released.
  const moving = objectLayer.state.moving;
  const dragged = moving?.dragging ? moving.object : null;
  for (const asset of current) {
    const object = known.get(asset.object_id);
    if (!object) {
      addAsset(asset);
      objects.at(-1).addedByOperator = true;
      if (asset.duplicated_from) objectLayer.addCopy(objects.at(-1));
      changed += 1;
    } else if (object.gone && object.splitAway) {
      // Back again, such as after Undo took back a delete, split or combine.
      object.splitAway = false;
      object.gone = false;
      object.pick.layers.enable(0);
      objectLayer.unerase(object);
      objectLayer.restorePiece(object);
      changed += 1;
    } else if (object !== dragged) {
      object.asset.name = asset.name;
      const posDiff = object.center.distanceTo(new THREE.Vector3(...asset.center)) > 0.001;
      const yawDiff = Math.abs((object.yaw || 0) - (asset.yaw || 0)) > 0.001;
      if (posDiff || yawDiff) {
        await objectLayer.ensurePiece(object);
        objectLayer.placeAt(object, asset.center, asset.yaw ?? 0);
        changed += 1;
      }
    }
  }
  if (changed) $("status").textContent = `Restored ${changed} saved change(s) from the backend`;
}

// Start just inside the door, facing into the room, the way a technician arrives. Uses the detected
// door, so it follows the extraction. Without one, or with ?start=centre, the scan's own start.
const DOOR_STEP_IN = 1.2; // metres into the room from the door's middle
function doorStart(data) {
  if (["centre", "center"].includes(params.get("start"))) return null;
  const door = data.assets.find((asset) => asset.label === "door");
  if (!door) return null;
  const middle = new THREE.Vector3(...(data.start ?? [0, 0, 0])); // the room's middle, roughly
  const at = new THREE.Vector3(...door.center);
  const inward = middle.sub(at).setY(0);
  if (inward.lengthSq() < 1e-6) return null;
  inward.normalize();
  const point = at.clone().addScaledVector(inward, DOOR_STEP_IN);
  point.y = data.floor_y ?? 0;
  return { point, inward };
}

// Take back the latest change: the backend replays the others, and the viewer catches up.
async function undoLast() {
  hideManipBar();
  let reply;
  try {
    const response = await fetch("/api/changes/undo", { method: "POST" });
    reply = await response.json();
    if (!response.ok) throw new Error(reply.detail ?? `error ${response.status}`);
  } catch (error) {
    $("status").textContent = `Nothing undone: ${error.message}`;
    return;
  }
  // The viewer keeps its own list of what it has sent; drop the change it just lost.
  const sent = objectLayer.state.changes;
  const last = sent.at(-1);
  if (last && last.op === reply.undone.op && last.object_id === reply.undone.object_id) {
    sent.pop();
    route.state.posted = Math.min(route.state.posted, sent.length);
  }
  await syncWithBackend();
  if (route.state.target) await route.plan(route.state.target, route.state.start);
  const what = { remove: "delete", move: "move", rotate: "turn" }[reply.undone.op] ?? reply.undone.op;
  $("status").textContent = `Undid the ${what} of ${reply.undone.object_id ?? "an object"}`;
}

// Ask the backend whether an object can stand here. Without a backend, nothing can be saved anyway.
async function checkMove(object, position, yaw = 0) {
  try {
    const id = encodeURIComponent(object.asset.object_id);
    const response = await fetch(`/api/objects/${id}/check-move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position, yaw }),
    });
    if (response.ok) return await response.json();
  } catch {
    // Handled below, the same as an error reply.
  }
  return { ok: true, reason: "", blockers: [] };
}

// What the voice copilot can do, through the same code as the buttons. See app/api/commands.py.
function commandHandlers() {
  const find = (id) => {
    const object = objects.find((o) => o.asset.object_id === id && !o.gone);
    if (!object) throw new Error(`No object ${id}`);
    return object;
  };
  const press = (id) => () => $(id).click();
  // Buttons toggle, so only press one if it isn't in the state asked for.
  const pressIf = (needed, id) => {
    if (needed) $(id).click();
  };
  const open = (id, button) => {
    const object = find(id);
    showInfo(object);
    const control = $(button);
    if (control.hidden || control.disabled) throw new Error(`${name(object.asset)} can't do that here.`);
    control.click();
  };
  const needsMovable = (id) => {
    const object = find(id);
    if (object.asset.mobility !== "movable") throw new Error(`${name(object.asset).replace(/\?$/, "")} is fixed, so it can't be moved.`);
  };
  const views = ["scan", "both", "objects"];
  return {
    select: ({ object_id }) => showInfo(find(object_id)),
    focus_object: ({ object_id }) => goLookAt(find(object_id)),
    move_by: ({ object_id, metres, direction }) => {
      needsMovable(object_id);
      return moveBy(find(object_id), metres, direction);
    },
    move_near: ({ object_id, near }) => {
      needsMovable(object_id);
      return moveNear(find(object_id), near);
    },
    set_stage: ({ stage }) => stages.set(stage),
    next_stage: () => stages.next(),
    // Val and voice start the Watch version: nobody is at the screen to choose.
    start_demo: () => {
      tour.start("watch");
    },
    stop_demo: () => tour.stop(),
    set_filter: ({ types, conditions, mobility }) => {
      filters.set({ types, conditions, mobility });
      return { ok: true, message: $("filter-count").textContent };
    },
    hide_types: ({ types }) => filters.hideTypes(types),
    clear_filters: () => filters.clear(),
    set_alerts: ({ level }) => filters.setAlerts(level),
    open_map: () => plan.open(),
    expand_map: () => plan.expand(),
    close_map: () => plan.close(),
    open_list: () => objectList.open(),
    close_list: () => objectList.close(),
    open_filters: () => ($("filter-panel").hidden = false),
    find_on_map: async ({ text }) => {
      await plan.expand();
      $("plan-search").value = text;
      plan.search(text);
    },
    close_panels: () => {
      $("info-close").click();
      $("copilot-close").click();
    },
    route_to: ({ object_id }) => routeTo(find(object_id)),
    go_to_fault: press("go-fault"),
    clear_route: press("clear-route"),
    walk_route: () => pressIf(!route.state.walking, "follow"),
    stop_walking: () => pressIf(route.state.walking, "follow"),
    set_profile: ({ profile }) => {
      if (!["person", "robot"].includes(profile)) throw new Error("Use person or robot");
      pressIf(route.state.profile !== profile, "profile");
    },
    set_mode: ({ mode }) => {
      if (!["walk", "fly"].includes(mode)) throw new Error("Use walk or fly");
      pressIf(walk !== (mode === "walk"), "mode");
    },
    set_boxes: ({ on }) => pressIf(boxesOn !== on, "boxes"),
    set_range: ({ metres }) => {
      if (!RANGES.includes(metres)) throw new Error(`Use one of ${RANGES.join(", ")} m`);
      range = metres;
      $("range").textContent = `Range ${range} m`;
    },
    set_view: ({ view }) => {
      if (!views.includes(view)) throw new Error(`Use one of ${views.join(", ")}`);
      objectLayer.setView(view);
      $("view-mode").textContent = view[0].toUpperCase() + view.slice(1);
    },
    set_apart: ({ on }) => pressIf(objectLayer.state.apart !== on, "apart"),
    reset_view: press("reset"),
    open_copilot: press("open-copilot"),
    ask_copilot: ({ question }) => copilot.open(question),
    move_object: ({ object_id, position }) => {
      const object = find(object_id);
      return objectLayer.moveTo(object, position);
    },
    rotate_object: ({ object_id, degrees }) => {
      const object = find(object_id);
      return objectLayer.moveTo(object, undefined, (degrees * Math.PI) / 180);
    },
    turn_object: ({ object_id, degrees }) => {
      const object = find(object_id);
      return objectLayer.moveTo(object, undefined, (object.yaw || 0) + (degrees * Math.PI) / 180);
    },
    start_move: ({ object_id }) => {
      needsMovable(object_id);
      open(object_id, "move");
    },
    start_rotate: ({ object_id }) => {
      needsMovable(object_id);
      open(object_id, "move"); // Rotate is a mode of Move now
      $("manip-mode-rotate").click();
    },
    finish_moving: press("manip-done"),
    undo_changes: press("reset-moves"),
    duplicate_object: ({ object_id }) => duplicateObject(objects.find((o) => o.asset.object_id === object_id)),
    rename_object: ({ object_id, name: text }) =>
      renameObject(objects.find((o) => o.asset.object_id === object_id), text),
    delete_object: ({ object_id }) => deleteObject(objects.find((o) => o.asset.object_id === object_id)),
    set_bim: ({ on }) => {
      if (!bim) throw new Error("No BIM model: run make bim");
      pressIf(bim.state.active !== on, "bim");
    },
    start_add: press("add-object"),
    start_split: ({ object_id }) => open(object_id, "split-object"),
    start_combine: ({ object_id }) => open(object_id, "combine-object"),
  };
}

async function load() {
  const data = await (await fetch("assets.json")).json();
  faultTag = data.fault_tag ?? faultTag;
  // The demo's critical device: one press routes there, whichever it is.
  $("go-fault").textContent = "Go to critical";
  if (data.up) {
    const up = new THREE.Vector3(...data.up).normalize();
    root.quaternion.setFromUnitVectors(up, new THREE.Vector3(0, 1, 0));
    root.updateMatrixWorld(true);
  }
  data.assets.forEach(addAsset);

  // Floor and start are in scene coordinates; convert to the upright world.
  const floor = root.localToWorld(new THREE.Vector3(0, data.floor_y ?? 0, 0)).y;
  eyeY = floor + EYE_HEIGHT;
  root.updateMatrixWorld(true);
  const door = doorStart(data);
  // Say so, rather than start somewhere else without a word.
  if (!door && params.get("start") === null) {
    $("status").textContent = "No door among the objects, so this starts in the middle of the room";
  }
  const start = door ? door.point.toArray() : (data.start ?? [0, data.floor_y ?? 0, 0]);
  startPos = root.localToWorld(new THREE.Vector3(...start));
  startPos.y = eyeY;
  camera.position.copy(startPos);
  if (door) {
    const ahead = door.inward.clone().transformDirection(root.matrixWorld).setY(0).normalize();
    camera.lookAt(startPos.clone().add(ahead));
  }
  startTurn = camera.quaternion.clone();

  const sceneFile = await pickScene();
  const splat = new SplatMesh({
    url: sceneFile.url,
    lod: LOD,
    onProgress: (event) => {
      if (!event.total) return;
      const done = Math.min(event.loaded / event.total, 1);
      $("loading-bar").firstElementChild.style.width = `${Math.round(done * 100)}%`;
      if (done === 1) $("loading-text").textContent = "Preparing the room...";
    },
  });
  root.add(splat);
  renderer.setAnimationLoop(animate);
  await splat.initialized;
  $("loading").hidden = true;
  const count = splat.packedSplats?.numSplats || splat.splats?.numSplats; // 0 or missing with LOD
  if (DEBUG) {
    console.info(
      `${data.assets.length} objects, ${sceneFile.label} scene, ${count ?? "?"} splats, res ${RES}, LOD ${LOD}`,
    );
  }
  $("status").textContent = TABLET
    ? "Tap a device to see it, or ask Val. Use the circle to walk."
    : "Click a device to see it, or ask Val. Drag to look, WASD to move.";

  objectLayer = await setupObjects({
    root,
    scene,
    camera,
    canvas,
    splat,
    objects,
    floorY: data.floor_y ?? 0,
    onChange: (changes) => {
      if (!changes.length) {
        $("status").textContent = "Everything's back as scanned.";
        removeAdded();
      }
      route.syncChanges(changes);
    },
    checkMove,
    onMessage: (message) => ($("status").textContent = message),
    onBlocked: (blocked) => $("hud").classList.toggle("blocked", blocked),
    onMoveCancelled: () => {
      if (route?.state.target) route.plan(route.state.target, route.state.start);
    },
  });
  route = setupRoute({
    root,
    camera,
    floorY: data.floor_y ?? 0,
    getEyeY: () => eyeY,
    // A collision warning says more than a route refusal caused by that same bad spot.
    onMessage: (message) => {
      if (!$("hud").classList.contains("blocked")) $("status").textContent = message;
    },
    onOutOfStep: syncWithBackend,
    // Reaching the faulty device starts the diagnosis, without being asked.
    onArrive: (target) => {
      if (kind(target.asset) !== "fault") return;
      copilot.open(`What's wrong with ${target.name.replace(/\?$/, "")}?`);
    },
  });
  $("go-fault").hidden = !objects.some((o) => kind(o.asset) === "fault");
  plan = setupPlan({
    wake: () => pacing.wake(),
    ui: {
      panel: $("plan"),
      canvas: $("plan-canvas"),
      search: $("plan-search"),
      pipes: $("plan-pipes"),
      legend: $("plan-legend"),
      note: $("plan-note"),
      dxf: $("plan-dxf"),
    },
    objects,
    root,
    camera,
    route,
    getSelected: () => selected,
    nameOf: (object) => name(object.asset),
    filters: {
      isActive: () => Boolean(filters?.isActive()),
      passes: (object) => !filters || filters.passes(object),
    },
    onSelect: showInfo,
  });
  $("open-plan").onclick = () => plan.toggle();
  $("plan-expand").onclick = () => plan.expand();
  $("plan-hide").onclick = () => plan.close();
  // A minimap from the start with a mouse. A small touch screen has less room, so it's a toggle.
  if (!TABLET) plan.open();
  filters = setupFilters({
    ui: {
      panel: $("filter-panel"),
      button: $("open-filters"),
      types: $("filter-types"),
      conditions: $("filter-conditions"),
      mobility: $("filter-mobility"),
      alerts: $("filter-alerts"),
      count: $("filter-count"),
      clear: $("filter-clear"),
      close: $("filter-close"),
    },
    objects,
    onChange: (stage, text) => {
      $("status").textContent = text;
      lastChosen = 0;
      objectList?.refresh();
      pacing.wake();
    },
  });
  objectList = setupObjectList({
    filters,
    panel: $("object-list"),
    list: $("object-rows"),
    search: $("object-search"),
    sort: $("object-sort"),
    unlinked: $("object-unlinked"),
    count: $("object-count"),
    objects,
    nameOf: (object) => name(object.asset),
    onSelect: (object) => {
      if (window.innerWidth < 700) objectList.close();
      goLookAt(object);
    },
  });
  $("open-list").onclick = () => objectList.toggle();
  $("focus-object").onclick = () => selected && goLookAt(selected);
  alerts = setupAlerts({
    filters,
    isHidden: () => Boolean(stages?.isQuiet()), // Only the real view shows the room's state
    root,
    camera,
    objects,
    layer: $("alert-badges"),
    nameOf: (object) => name(object.asset),
    onEnter: (object, state, distance) => {
      $("status").textContent = `Nearby: ${name(object.asset)}, ${state.toLowerCase()}, ${distance.toFixed(1)} m away`;
    },
  });
  $("object-list-close").onclick = () => objectList.close();
  $("plan-close").onclick = () => plan.collapse();
  // These work in the 3D view, so the Plan screen makes way for them.
  for (const id of ["move", "split-object", "combine-object"]) {
    $(id).addEventListener("click", () => plan.collapse());
  }
  $("profile").hidden = false;
  const views = ["scan", "both", "objects"];
  $("view-mode").onclick = () => {
    const next = views[(views.indexOf(objectLayer.state.view) + 1) % views.length];
    objectLayer.setView(next);
    $("view-mode").textContent = next[0].toUpperCase() + next.slice(1);
  };
  $("apart").onclick = () => {
    objectLayer.setApart(!objectLayer.state.apart);
    $("apart").textContent = objectLayer.state.apart ? "Together" : "Apart";
  };
  $("reset-moves").onclick = () => {
    hideManipBar();
    objectLayer.resetMoves();
  };
  $("undo-last").onclick = undoLast;
  bim = await setupBim({
    isShown: (object) => !filters || filters.passes(object),
    isFiltering: () => Boolean(filters?.isActive()),
    root,
    renderer,
    objects,
    faultTag,
    floorY: data.floor_y ?? 0,
    // Walls and the floor have no scan object, so only the BIM panel describes them.
    onSelectObject: (object) => (object ? showInfo(object) : ($("info").hidden = true)),
    onMessage: (message) => ($("status").textContent = message),
  }).catch((err) => {
    console.error("BIM model failed to load", err);
    return null;
  });
  let viewBeforeBim = "scan";
  $("bim").hidden = !bim;
  $("bim").onclick = () => {
    const on = !bim.state.active;
    hideManipBar();
    if (on) viewBeforeBim = objectLayer.state.view;
    objectLayer.setView(on ? "bim" : viewBeforeBim);
    bim.setActive(on);
    $("bim").textContent = on ? "Exit BIM" : "BIM";
    $("view-mode").disabled = on;
    $("apart").disabled = on;
    $("status").textContent = on
      ? `BIM model: ${bim.elementCount} elements, simulated from the scan`
      : "Back to the scan";
  };
  // Starting states from the URL, for screenshots and rehearsals.
  if (params.has("view")) {
    objectLayer.setView(params.get("view"));
    $("view-mode").textContent = params.get("view");
  }
  if (params.get("apart") === "1") {
    objectLayer.setApart(true);
    $("apart").textContent = "Together";
  }
  await syncWithBackend();
  setupCommands(commandHandlers());
  stages = setupViews({
    root,
    bim,
    press: (id) => $(id).click(),
    button: $("next-view"),
    onChange: () => {
      lastChosen = 0;
      pacing.wake();
    },
  });
  tour = setupTour({
    ui: {
      panel: $("tour"),
      title: $("tour-title"),
      text: $("tour-text"),
      count: $("tour-count"),
      pause: $("tour-pause"),
      next: $("tour-next"),
      stop: $("tour-stop"),
      back: $("tour-back"),
      how: $("tour-how"),
      show: $("tour-show"),
      choice: $("tour-choice"),
      watch: $("tour-watch"),
      tryIt: $("tour-try"),
      spot: $("tour-spot"),
    },
    handlers: commandHandlers(),
    press: (id) => $(id).click(),
    view: {
      objects,
      filters,
      plan,
      route,
      copilot,
      objectList,
      views: stages,
      nameOf: (object) => name(object.asset).replace(/\?$/, ""),
      fault: () => objects.find((o) => kind(o.asset) === "fault" && !o.gone),
      goLookAt,
      range: () => range,
      moveObject: (object, position, yaw) => objectLayer.moveTo(object, position, yaw),
      placeAt: (object, center, yaw) => objectLayer.placeAt(object, center, yaw),
      checkMove: (object, position, yaw) => checkMove(object, position, yaw),
      select: (object) => showInfo(object),
      undoLast,
      closeInfo: () => $("info-close").click(),
      closeFilters: () => ($("filter-panel").hidden = true),
      openFilters: () => ($("filter-panel").hidden = false),
      camera,
      wake: () => pacing.wake(),
      walking: () => walk,
      boxesOn: () => boxesOn,
      selected: () => selected,
      changeCount: () => objectLayer.state.changes.length,
      alertsActive: () => Boolean(alerts?.isActive()),
      hasBim: () => Boolean(bim),
      bimActive: () => Boolean(bim?.state.active),
    },
  });
  $("start-tour").onclick = () => tour.start();
  $("help-tutorial").onclick = () => {
    $("help-panel").hidden = true;
    tour.start();
  };
  if (params.has("demo")) tour.start("watch");
  else if (firstVisit()) tour.start(); // asks Watch or Try it, and Close leaves everything as it was
  window.plantViewer = { views: stages, tour, scene, root, filters, objects, objectLayer, camera, route, copilot, showInfo, adder, bim, plan, pacing }; // For browser tests and debugging.
  if (params.has("camera")) {
    const [x, y, z, yaw, pitch] = params.get("camera").split(",").map(Number);
    camera.position.set(x, y, z);
    camera.rotation.set(pitch, yaw, 0, "YXZ");
    walk = false;
  }
}

// The tutorial offers itself once per browser. Storage can be blocked: then it just doesn't offer.
function firstVisit() {
  if (params.has("camera") || params.has("notour")) return false;
  try {
    if (localStorage.getItem("tutorial-offered")) return false;
    localStorage.setItem("tutorial-offered", "1");
    return true;
  } catch {
    return false;
  }
}

load().catch((err) => {
  $("status").textContent = `Failed to load: ${err.message}`;
  console.error(err);
});
