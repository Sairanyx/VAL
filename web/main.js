// Plant room viewer: walk through the splat scene like a camera feed, with object boxes and labels.
// Data: /scene.ply (Gaussian splat) and /assets.json (same format as fixtures/sample_assets.json),
// both served by web/serve.py.
import * as THREE from "three";
import { SparkControls, SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { setupAddObject } from "./addobject.js";
import { setupCopilot } from "./copilot.js";
import { setupObjects } from "./objects.js";
import { setupPhone } from "./phone.js";
import { setupRoute } from "./route.js";

const FAULT_TAG = "P-005"; // the pre-chosen faulty device (docs/PLAN.md)
const EYE_HEIGHT = 1.6; // metres above the floor in walk mode (scene units look close to metres)
const RANGES = [2, 3, 5, 10]; // metres the Range button cycles through, for frames and labels
const MAX_LABELS = 8;
const MAX_BOXES = 15;
const BACKGROUND_LABELS = new Set(["pipe", "pipe fitting", "cable", "hose", "object"]);

// Speed settings, changeable in the URL without editing code, e.g. ?res=0.5&splats=300000
//   res     render resolution relative to the screen (default 1; 0.5 is about 4x fewer pixels)
//   lod     1 = level of detail on: far-away areas use fewer, bigger splats (default 1)
//   splats  how many splats LOD aims to draw per frame (default: Spark's choice for the device)
const params = new URLSearchParams(location.search);
const RES = Number(params.get("res") ?? 1);
const LOD = params.get("lod") !== "0";
const LOD_SPLATS = params.has("splats") ? Number(params.get("splats")) : undefined;

const $ = (id) => document.getElementById(id);
const canvas = $("view");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
// Rendering every splat at full high-DPI resolution is the main cost; 1 pixel per CSS pixel is enough.
renderer.setPixelRatio(RES);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 200);
scene.add(new SparkRenderer({ renderer, lodSplatCount: LOD_SPLATS }));

// The scene's +y points down. Turn it upright once here, and put everything in scene
// coordinates inside `root`, so file coordinates can be used as they are.
const root = new THREE.Group();
root.rotation.x = Math.PI;
scene.add(root);

const controls = new SparkControls({ canvas });
const phone = setupPhone({
  camera,
  button: $("phone"),
  joystick: $("joystick"),
  onMessage: (msg) => ($("status").textContent = msg),
});
const raycaster = new THREE.Raycaster();
const objects = []; // { asset, box, pick, label, center }
let walk = true;
let eyeY = EYE_HEIGHT;
let startPos = new THREE.Vector3(0, EYE_HEIGHT, 0);
let objectLayer = null;
let route = null;
let selected = null;
let boxesOn = true;
let range = Number(params.get("range") ?? 3);

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
  if (asset.mapping?.tag === FAULT_TAG) return "fault";
  return asset.mapping ? "mapped" : "plain";
}
const COLORS = { fault: 0xff4d4f, mapped: 0x38bdf8, plain: 0xd1d5db };

// Links made by rule aren't real identities, so they're shown as a question.
function name(asset) {
  const link = asset.mapping;
  if (!link) return asset.label;
  return link.method?.startsWith("procedural") ? `${link.tag}?` : link.tag;
}

function addAsset(asset) {
  const min = new THREE.Vector3(...asset.bbox_min);
  const max = new THREE.Vector3(...asset.bbox_max);
  const size = max.clone().sub(min);
  const mid = min.clone().add(max).multiplyScalar(0.5);
  const geom = new THREE.BoxGeometry(size.x, size.y, size.z);

  const box = new THREE.LineSegments(
    new THREE.EdgesGeometry(geom),
    new THREE.LineBasicMaterial({ color: COLORS[kind(asset)] }),
  );
  box.position.copy(mid);
  root.add(box);

  // Invisible solid box, so taps and the crosshair can hit the object.
  const pick = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ visible: false }));
  pick.position.copy(mid);
  pick.userData.index = objects.length;
  root.add(pick);

  const label = document.createElement("div");
  label.className = `label ${kind(asset)}`;
  $("labels").append(label);

  const volume = Math.max(size.x * size.y * size.z, 1e-6);
  objects.push({ asset, box, pick, label, volume, center: new THREE.Vector3(...asset.center) });
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
    ["Object", a.object_id],
    ["Tag", m?.tag ?? "not mapped"],
    ["Asset", m?.asset_id],
    ["Mapped by", m ? `${m.method}, confidence ${m.confidence}` : undefined],
  ].filter(([, v]) => v !== undefined);
  $("info-body").innerHTML =
    `<h2>${name(a)}${kind(a) === "fault" ? " — fault" : ""}</h2><dl>` +
    rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") +
    "</dl>";
  selected = obj;
  $("move").hidden = a.mobility !== "movable" || !objectLayer;
  $("route-here").hidden = !route;
  $("ask").hidden = false;
  showCondition(obj);
  $("info").hidden = false;
}
$("info-close").onclick = () => ($("info").hidden = true);

async function routeTo(obj) {
  $("info").hidden = true;
  $("status").textContent = `Planning a route to ${name(obj.asset)}...`;
  const found = await route.plan({ asset: obj.asset, center: obj.center, name: name(obj.asset) });
  $("follow").hidden = !found;
  $("clear-route").hidden = !found;
  $("follow").textContent = "Walk route";
  selected = obj;
}
$("route-here").onclick = () => selected && routeTo(selected);
const copilot = setupCopilot({
  panel: $("copilot"),
  form: $("copilot-form"),
  input: $("copilot-input"),
  answer: $("copilot-answer"),
  close: $("copilot-close"),
  getObject: () => selected,
});
$("ask").onclick = () => {
  $("info").hidden = true;
  const about = selected ? name(selected.asset) : "this";
  copilot.open(`Why is ${about} flagged, and what should I check first?`);
};
$("open-copilot").onclick = () => copilot.open();

const adder = setupAddObject({
  canvas,
  root,
  camera,
  render: () => renderer.render(scene, camera),
  ui: {
    frame: $("select-frame"),
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
  onSaved: async (asset) => {
    addAsset(asset);
    const added = objects.at(-1);
    added.addedByOperator = true;
    selected = added;
    const added_text = `Added ${asset.object_id}: ${asset.label}, not confirmed`;
    $("status").textContent = added_text;
    if (route?.state.target) {
      await route.plan(route.state.target, route.state.start);
      $("status").textContent = `${added_text}. ${$("status").textContent}`;
    }
  },
});
$("add-object").onclick = () => adder.start();

// Undo removes operator-added objects too, because the backend's reset forgets them.
function removeAdded() {
  for (const object of objects) {
    if (!object.addedByOperator) continue;
    object.addedByOperator = false;
    object.gone = true;
    object.box.visible = false;
    object.pick.layers.disable(0);
    object.label.style.display = "none";
  }
}
$("go-fault").onclick = () => {
  const fault = objects.find((o) => kind(o.asset) === "fault");
  if (fault) routeTo(fault);
  else $("status").textContent = `No object is mapped to ${FAULT_TAG}`;
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
$("move").onclick = () => {
  if (objectLayer?.startMove(selected)) {
    $("info").hidden = true;
    $("status").textContent = `Drag ${name(selected.asset)} along the floor`;
  }
};

function hit(ndc) {
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects(objects.map((o) => o.pick));
  // A pipe's box can span the room, so the smallest box under the pointer is the likely target.
  const found = hits.map((h) => objects[h.object.userData.index]);
  return found.length ? found.reduce((a, b) => (b.volume < a.volume ? b : a)) : null;
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
  const ndc = new THREE.Vector2(
    (e.clientX / window.innerWidth) * 2 - 1,
    -(e.clientY / window.innerHeight) * 2 + 1,
  );
  const obj = hit(ndc);
  if (obj) showInfo(obj);
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
$("reset").onclick = () => {
  camera.position.copy(startPos);
  camera.quaternion.identity();
  phone.recenter();
};

// Draw a label over every object in front of the camera, like detections on a camera feed.
// Occlusion is ignored for now: an object behind a wall still gets a label.
const tmp = new THREE.Vector3();
function updateLabels() {
  // Everything within range competes for a few places, so the view stays readable: the fault and
  // the selection always show, then linked equipment, then other things, with pipes last.
  const visible = [];
  const nearby = [];
  const apart = objectLayer?.state.amount > 0;
  for (const o of objects) {
    if (o.gone) continue;
    const world = root.localToWorld(tmp.copy(o.center));
    const dist = world.distanceTo(camera.position);
    const ndc = world.project(camera);
    const onScreen = ndc.z < 1 && Math.abs(ndc.x) <= 1 && Math.abs(ndc.y) <= 1;
    o.label.style.display = "none";
    o.box.visible = false;
    const pinned = kind(o.asset) === "fault" || o === selected;
    if (!pinned && (dist > range || (apart && !o.shape))) continue;
    const rank = pinned ? 0 : o.asset.mapping ? 1 : BACKGROUND_LABELS.has(o.asset.label) ? 3 : 2;
    nearby.push({ o, dist, rank, pinned, onScreen, ndc: ndc.clone() });
  }
  nearby.sort((a, b) => a.rank - b.rank || a.dist - b.dist);
  const inView = nearby.filter((item) => item.onScreen);
  if (boxesOn && !apart) {
    for (const { o } of inView.slice(0, MAX_BOXES)) o.box.visible = true;
    for (const { o, pinned } of nearby) if (pinned) o.box.visible = true;
  }
  for (const item of inView) {
    // Unconfirmed objects keep their frame, but don't crowd the view with a generic tag.
    if (item.o.asset.label !== "object" || item.o.asset.mapping) visible.push(item);
  }
  for (const { o, dist, ndc } of visible.slice(0, MAX_LABELS)) {
    o.label.style.display = "block";
    o.label.style.left = `${((ndc.x + 1) / 2) * window.innerWidth}px`;
    o.label.style.top = `${((1 - ndc.y) / 2) * window.innerHeight}px`;
    const type = name(o.asset) === o.asset.label ? "" : `${o.asset.label} · `;
    o.label.innerHTML = `${name(o.asset)} <small>${type}${dist.toFixed(1)} m</small>`;
  }
  const looking = hit(new THREE.Vector2(0, 0));
  $("in-view").textContent =
    `${inView.length} object(s) within ${range} m` +
    (looking ? ` · looking at ${name(looking.asset)}` : "");
}

let frames = 0;
let lastFps = performance.now();
let lastFrame = performance.now();
function animate(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.1);
  lastFrame = now;
  // In phone mode the phone's rotation steers, so mouse/touch dragging must not fight it.
  const following = Boolean(route?.state.walking);
  const busy = objectLayer?.state.moving || adder.state.active || following;
  if (!phone.enabled && !busy) controls.update(camera);
  objectLayer?.update(dt);
  if (following) route.update(dt);
  else phone.update(dt);
  $("follow").textContent = following ? "Stop" : "Walk route";
  if (walk) camera.position.y = eyeY;
  renderer.render(scene, camera);
  updateLabels();
  frames++;
  if (now - lastFps > 1000) {
    const fps = Math.round((frames * 1000) / (now - lastFps));
    $("stats").textContent = `${fps} fps` + (phone.enabled ? ` · ${phone.steps} steps` : "");
    frames = 0;
    lastFps = now;
  }
}

async function load() {
  const data = await (await fetch("assets.json")).json();
  data.assets.forEach(addAsset);

  // Floor and start are in scene coordinates; convert to the upright world.
  const floor = root.localToWorld(new THREE.Vector3(0, data.floor_y ?? 0, 0)).y;
  eyeY = floor + EYE_HEIGHT;
  const start = data.start ?? [0, data.floor_y ?? 0, 0];
  startPos = root.localToWorld(new THREE.Vector3(...start));
  startPos.y = eyeY;
  camera.position.copy(startPos);

  const splat = new SplatMesh({ url: "scene.ply", lod: LOD });
  root.add(splat);
  renderer.setAnimationLoop(animate);
  await splat.initialized;
  const count = splat.packedSplats?.numSplats || splat.splats?.numSplats; // 0 or missing with LOD
  $("status").textContent =
    `${data.assets.length} objects · ${count ? `${count.toLocaleString()} splats · ` : ""}` +
    `res ${RES}, LOD ${LOD ? "on" : "off"}${LOD_SPLATS ? ` (${LOD_SPLATS})` : ""} · ` +
    "drag to look, WASD to move";

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
  });
  route = setupRoute({
    root,
    camera,
    floorY: data.floor_y ?? 0,
    getEyeY: () => eyeY,
    onMessage: (message) => ($("status").textContent = message),
  });
  $("go-fault").hidden = !objects.some((o) => kind(o.asset) === "fault");
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
  $("reset-moves").onclick = () => objectLayer.resetMoves();
  // Starting states from the URL, for screenshots and rehearsals.
  if (params.has("view")) {
    objectLayer.setView(params.get("view"));
    $("view-mode").textContent = params.get("view");
  }
  if (params.get("apart") === "1") {
    objectLayer.setApart(true);
    $("apart").textContent = "Together";
  }
  window.plantViewer = { objects, objectLayer, camera, route, copilot, showInfo, adder }; // For browser tests and debugging.
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
