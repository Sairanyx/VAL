// Plant room viewer: walk through the splat scene like a camera feed, with object boxes and labels.
// Data: /scene.ply (Gaussian splat) and /assets.json (same format as fixtures/sample_assets.json),
// both served by web/serve.py.
import * as THREE from "three";
import { SparkControls, SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { setupAddObject } from "./addobject.js";
import { setupBim } from "./bim.js";
import { setupCommands } from "./commands.js";
import { setupCopilot } from "./copilot.js";
import { setupHighlight } from "./highlight.js";
import { createHoverShell } from "./hover.js";
import { THIN_LABELS, pickFront } from "./pick.js";
import { setupObjects } from "./objects.js";
import { setupPacing } from "./pacing.js";
import { setupPhone } from "./phone.js";
import { setupPlan } from "./plan.js";
import { setupWalkXR, xrSupported } from "./xr.js";
import { setupRoute } from "./route.js";

let faultTag = "P-005"; // the pre-chosen faulty device, unless the scene's file names another
const EYE_HEIGHT = 1.6; // metres above the floor in walk mode (scene units look close to metres)
const RANGES = [2, 3, 5, 10]; // metres the Range button cycles through, for frames and labels
const MAX_BOXES = 15;
const BACKGROUND_LABELS = new Set(["pipe", "pipe fitting", "cable", "hose", "object"]);

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

const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
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
const phone = setupPhone({
  camera,
  button: $("phone"),
  joystick: $("joystick"),
  onMessage: (msg) => ($("status").textContent = msg),
});
const raycaster = new THREE.Raycaster();
const objects = []; // { asset, box, pick, label, center, yaw, baseSize }
const pacing = setupPacing({
  renderer,
  camera,
  baseRes: RES,
  adaptive: ADAPTIVE,
  isBusy: () =>
    phone.enabled ||
    Boolean(objectLayer?.state.moving) ||
    Boolean(adder?.state.active) ||
    Boolean(route?.state.walking) ||
    tracking.state.active,
  isDragging: () => Boolean(objectLayer?.state.moving?.dragging),
  isAnimated: () => Boolean(route?.state.route),
});
let walk = true;
let eyeY = EYE_HEIGHT;
let startPos = new THREE.Vector3(0, EYE_HEIGHT, 0);
let objectLayer = null;
let bim = null;
let route = null;
let plan = null;
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
const COLORS = { fault: 0xff4d4f, mapped: 0x38bdf8, plain: 0xd1d5db };

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
    new THREE.LineBasicMaterial({ color: COLORS[kind(asset)], transparent: true }),
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
    ["Why", a.label_reason],
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
$("duplicate-object").onclick = () => selected && duplicateObject(selected);
$("delete-object").onclick = askToDelete;
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

// Val's answers can point at objects, or ask for a route. Returns what went wrong, if anything.
async function runValActions(actions) {
  const find = (id) => objects.find((o) => o.asset.object_id === id && !o.gone);
  let problem = null;
  for (const action of actions) {
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
  speakButton: $("copilot-speak"),
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

// The main buttons stay few. Everything else waits behind More.
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

// Delete asks first, in the panel. Undo changes brings an object back.
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
  $("status").textContent = `Deleted ${text}. Undo changes in More brings it back.`;
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
    return;
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
    return;
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
  if (!$("more-menu").hidden) showMenu(false);
  else if (!$("rename-form").hidden) $("rename-form").hidden = true;
  else if (!$("delete-confirm").hidden) $("delete-confirm").hidden = true;
  else if (!$("add-panel").hidden || adder.state.active) $("add-cancel").click();
  else if (objectLayer?.state.moving) $("manip-done").click();
  else if (route?.state.walking) $("follow").click();
  else if (!$("copilot").hidden) $("copilot-close").click();
  else if (plan?.state.open) plan.close();
  else if (selected || !$("info").hidden) deselect();
  else return false;
  return true;
}
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") goBack();
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
    $("status").textContent = `Rotate ${name(selected.asset)}: Drag across screen, tap 45°, or twist with 2 fingers`;
  } else {
    $("status").textContent = `Move ${name(selected.asset)}: Drag along floor · Hold Shift to rotate`;
  }
}

$("move").onclick = () => {
  if (objectLayer?.startMove(selected)) {
    $("info").hidden = true;
    showManipBar("move");
  }
};
$("rotate").onclick = () => {
  if (objectLayer?.startRotate(selected)) {
    $("info").hidden = true;
    showManipBar("rotate");
  }
};
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
  raycaster.setFromCamera(ndc, camera);
  const candidates = objects
    .filter((o) => !o.gone && o.pick.layers.isEnabled(0))
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
  camera.position.copy(startPos);
  camera.rotation.set(0, 0, 0);
  camera.quaternion.set(0, 0, 0, 1);
};

const pos = new THREE.Vector3();
// Choosing what to show looks at every object, so it runs a few times a second. Placing what's
// shown runs every frame, as labels must stay on their objects.
const CHOOSE_EVERY = 200; // milliseconds
let lastChosen = 0;
let shownLabels = [];

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
    pos.copy(o.center).applyMatrix4(root.matrixWorld);
    const dist = camera.position.distanceTo(pos);
    if (dist > range) continue;
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
  if (boxesOn && !apart && !bim?.state.active) {
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
  inView.forEach((item, index) => {
    // Unconfirmed objects keep their frame, but don't crowd the view with a generic tag.
    if (item.o.asset.status === "new, unconfirmed") return;
    if (index >= MAX_LABELS && !item.pinned) return;
    next.add(item.o);
  });
  for (const o of objects) setLabel(o, name(o.asset), next.has(o));
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
  const busy = objectLayer?.state.moving || adder.state.active || following;
  // Typing in the Plan screen's search box shouldn't walk the viewer around. While tracking, the
  // device's own movement moves the camera, so the other controls stay out.
  const tracked = tracking.state.active;
  // Keys typed into Val or a name box are for that box, not for walking.
  const typingNow = isTyping();
  if (!phone.enabled && !busy && !tracked && !plan?.state.open && !typingNow) controls.update(camera);
  const stepTime = lastStep ? (now - lastStep) / 1000 : 0;
  lastStep = now;
  if (following && !tracked) route.update(stepTime);
  else if (!tracked) phone.update(stepTime);
  if (walk && !tracked) camera.position.y = eyeY;
  const hoverDue = now - lastHoverCheck > HOVER_EVERY;
  if (hoverDue && (hoverChanged || (hoverAt && pacing.isMoving()))) {
    hoverChanged = false;
    lastHoverCheck = now;
    if (!plan?.state.open) updateHover();
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
  if (plan?.state.open) {
    plan.draw(); // The room is covered, so there's no need to draw it as well.
  } else {
    renderer.render(scene, camera);
    tracking.update();
    if (now - lastChosen > CHOOSE_EVERY) {
      lastChosen = now;
      chooseLabels();
    }
    placeLabels();
  }
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
    saved.changes.filter((change) => change.op === "remove").map((change) => change.object_id),
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
    showInfo(find(id));
    $(button).click();
  };
  const views = ["scan", "both", "objects"];
  return {
    select: ({ object_id }) => showInfo(find(object_id)),
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
    start_move: ({ object_id }) => open(object_id, "move"),
    start_rotate: ({ object_id }) => open(object_id, "rotate"),
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
  $("go-fault").textContent = `Go to ${faultTag}`;
  if (data.up) {
    const up = new THREE.Vector3(...data.up).normalize();
    root.quaternion.setFromUnitVectors(up, new THREE.Vector3(0, 1, 0));
    root.updateMatrixWorld(true);
  }
  data.assets.forEach(addAsset);

  // Floor and start are in scene coordinates; convert to the upright world.
  const floor = root.localToWorld(new THREE.Vector3(0, data.floor_y ?? 0, 0)).y;
  eyeY = floor + EYE_HEIGHT;
  const start = data.start ?? [0, data.floor_y ?? 0, 0];
  startPos = root.localToWorld(new THREE.Vector3(...start));
  startPos.y = eyeY;
  camera.position.copy(startPos);

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
      $("status").textContent = `${changes.length} object(s) moved`;
      if (!changes.length) removeAdded();
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
  });
  $("go-fault").hidden = !objects.some((o) => kind(o.asset) === "fault");
  plan = setupPlan({
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
    getFaultTag: () => faultTag,
    getSelected: () => selected,
    nameOf: (object) => name(object.asset),
    onSelect: showInfo,
  });
  $("open-plan").onclick = () => plan.open();
  $("plan-close").onclick = () => plan.close();
  // These work in the 3D view, so the Plan screen makes way for them.
  for (const id of ["move", "split-object", "combine-object"]) {
    $(id).addEventListener("click", () => plan.close());
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
  bim = await setupBim({
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
  window.plantViewer = { objects, objectLayer, camera, route, copilot, showInfo, adder, bim, plan, pacing }; // For browser tests and debugging.
  if (params.has("camera")) {
    const [x, y, z, yaw, pitch] = params.get("camera").split(",").map(Number);
    camera.position.set(x, y, z);
    camera.rotation.set(pitch, yaw, 0, "YXZ");
    walk = false;
  }
}

load().catch((err) => {
  $("status").textContent = `Failed to load: ${err.message}`;
  console.error(err);
});
