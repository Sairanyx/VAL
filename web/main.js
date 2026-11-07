// Plant room viewer: walk through the splat scene like a camera feed, with object boxes and labels.
// Data: /scene.ply (Gaussian splat) and /assets.json (same format as fixtures/sample_assets.json),
// both served by web/serve.py.
import * as THREE from "three";
import { SparkControls, SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { setupAddObject } from "./addobject.js";
import { setupCommands } from "./commands.js";
import { setupBim } from "./bim.js";
import { setupCopilot } from "./copilot.js";
import { setupHighlight } from "./highlight.js";
import { setupObjects } from "./objects.js";
import { setupPhone } from "./phone.js";
import { setupWalkXR, xrSupported } from "./xr.js";
import { setupPlan } from "./plan.js";
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
const params = new URLSearchParams(location.search);
//   tablet  1 or 0 forces the touch layout and lighter defaults. Default: on for touch screens
const TABLET = params.has("tablet")
  ? params.get("tablet") === "1"
  : window.matchMedia("(pointer: coarse)").matches;
document.body.classList.toggle("tablet", TABLET);
const MAX_LABELS = TABLET ? 5 : 8;
const RES = Number(params.get("res") ?? (TABLET ? TABLET_RES : 1));
const LOD = params.get("lod") !== "0";
const LOD_SPLATS = params.has("splats")
  ? Number(params.get("splats"))
  : TABLET
    ? TABLET_SPLATS
    : undefined;
// Tablet mode also loads the light scene (every splat, base colour only, about 4x smaller) when
// the server offers one. ?scene=full or ?scene=light overrides the choice on any device.
async function pickScene() {
  const wanted = params.get("scene") ?? (TABLET ? "light" : "full");
  if (wanted === "light") {
    const head = await fetch("scene-light.ply", { method: "HEAD" }).catch(() => null);
    if (head?.ok) return { url: "scene-light.ply", label: "light" };
  }
  return { url: "scene.ply", label: "full" };
}

const PANEL_CONTROLS = "button, a, input, select, textarea, label, summary, form";
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
  if (!link) return asset.label;
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
  const pick = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ visible: false }));
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
  $("ask").hidden = false;
  showCondition(obj);
  $("info").hidden = false;
}
// A tap on the scene opens a window, and the browser then sends its own click to the same spot.
// That click would land on the new window and close it at once (or press one of its buttons), so
// windows ignore clicks that arrive just after a tap on the scene.
const GHOST_CLICK_MS = 500;
let lastSceneTap = 0;

// On a tablet there's no close button: tapping a window anywhere except its controls closes it.
function closeOnTap(panel, close) {
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
  panel.addEventListener("click", (event) => {
    if (document.body.classList.contains("tablet") && !event.target.closest(PANEL_CONTROLS)) {
      close.click();
    }
  });
}
closeOnTap($("info"), $("info-close"));
closeOnTap($("copilot"), $("copilot-close"));
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
}
$("route-here").onclick = () => selected && routeTo(selected);
const copilot = setupCopilot({
  button: $("open-copilot"),
  askButton: $("ask"),
  panel: $("copilot"),
  form: $("copilot-form"),
  input: $("copilot-input"),
  answer: $("copilot-answer"),
  close: $("copilot-close"),
  getSelected: () => selected,
  name,
});

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
    hideObject(parent);
    parent.splitAway = true;
    for (const part of parts) {
      addAsset(part);
      objects.at(-1).addedByOperator = true;
    }
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
    for (const object of [first, other]) {
      hideObject(object);
      object.splitAway = true;
    }
    addAsset(combined);
    selected = objects.at(-1);
    selected.addedByOperator = true;
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

function hideObject(object) {
  objectLayer?.dropPiece(object);
  object.gone = true;
  object.box.visible = false;
  object.pick.layers.disable(0);
  object.label.style.display = "none";
}

// Undo removes operator-added objects too, because the backend's reset forgets them.
function removeAdded() {
  for (const object of objects) {
    if (object.addedByOperator) {
      object.addedByOperator = false;
      hideObject(object);
    } else if (object.splitAway) {
      // The backend's reset brings back whatever was split.
      object.splitAway = false;
      object.gone = false;
      object.pick.layers.enable(0);
      objectLayer?.restorePiece(object);
    }
  }
}
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

function hideManipBar() {
  $("manip-bar").hidden = true;
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
  if (selected) $("status").textContent = `Saved ${name(selected.asset)}`;
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
function updateLabels() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const apart = objectLayer?.state.apart;
  for (const o of objects) {
    o.box.visible = false;
    o.label.style.display = "none";
  }

  const nearby = [];
  for (const o of objects) {
    if (o.gone) continue;
    pos.copy(o.center);
    root.localToWorld(pos);
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
  for (const item of inView) {
    // Unconfirmed objects keep their frame, but don't crowd the view with a generic tag.
    if (item.o.asset.status === "new, unconfirmed") continue;
    if (inView.indexOf(item) >= MAX_LABELS && !item.pinned) continue;
    const label = item.o.label;
    label.textContent = name(item.o.asset);
    label.style.left = `${item.x}px`;
    label.style.top = `${item.y}px`;
    label.style.display = "block";
  }
}

let lastTime = 0;
let frames = 0;
let lastFps = performance.now();
function animate(now) {
  const dt = lastTime ? (now - lastTime) / 1000 : 0;
  lastTime = now;
  const following = Boolean(route?.state.walking);
  const busy = objectLayer?.state.moving || adder.state.active || following;
  // While tracking, the device's own movement moves the camera, so the other controls stay out.
  // Typing in the Plan screen's search box shouldn't walk the viewer around either.
  const tracked = tracking.state.active;
  if (!phone.enabled && !busy && !tracked && !plan?.state.open) controls.update(camera);
  objectLayer?.update(dt);
  highlight.update();
  bim?.update();
  if (following && !tracked) route.update(dt);
  else if (!tracked) phone.update(dt);
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
  $("follow").textContent = following ? "Stop" : "Walk route";
  if (walk && !tracked) camera.position.y = eyeY;
  if (plan?.state.open) {
    plan.draw(); // The room is covered, so there's no need to draw it as well.
  } else {
    renderer.render(scene, camera);
    tracking.update();
    updateLabels();
  }
  frames++;
  if (now - lastFps > 1000) {
    const fps = Math.round((frames * 1000) / (now - lastFps));
    $("stats").textContent = `${fps} fps` + (phone.enabled ? ` · ${phone.steps} steps` : "");
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
  for (const object of objects) {
    if (!present.has(object.asset.object_id)) {
      hideObject(object);
      object.splitAway = true;
      changed += 1;
    }
  }
  for (const asset of current) {
    const object = known.get(asset.object_id);
    if (!object) {
      addAsset(asset);
      objects.at(-1).addedByOperator = true;
      changed += 1;
    } else {
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
  const splat = new SplatMesh({ url: sceneFile.url, lod: LOD });
  root.add(splat);
  renderer.setAnimationLoop(animate);
  await splat.initialized;
  const count = splat.packedSplats?.numSplats || splat.splats?.numSplats; // 0 or missing with LOD
  $("status").textContent =
    `${data.assets.length} objects · ${sceneFile.label} scene · ` +
    `${count ? `${count.toLocaleString()} splats · ` : ""}` +
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
  }).catch((err) => {
    console.error("BIM model failed to load", err);
    return null;
  });
  let viewBeforeBim = "scan";
  $("bim").hidden = !bim;
  $("bim").onclick = () => {
    const on = !bim.state.active;
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
  window.plantViewer = { objects, objectLayer, camera, route, copilot, showInfo, adder, bim, plan }; // For browser tests and debugging.
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
